import sys
from antlr4 import *
from antlr4.tree.Tree import *
from antlr4.atn.PredictionMode import PredictionMode
from antlr4.error.ErrorStrategy import BailErrorStrategy

from pythonql.parser.CustomLexer import CustomLexer
from pythonql.parser.Errors import CustomErrorStrategy, CustomErrorListener, BufferedErrorListener
from pythonql.parser.PythonQLParser import PythonQLParser
from functools import reduce
import time

def str_encode(string):
    res = ""
    for ch in string:
        if ch == '"':
            res += chr(92)
            res += '"'
        elif ch == chr(92):
            res += chr(92)
            res += chr(92)
        else:
            res += ch
    return res

# The preprocessor inserts tokens into
# the token stream, produced by traversing
# the parse tree.
class MyToken(TerminalNodeImpl):
    def __init__(self,text):
        self.text = text
    def getText(self):
        return self.text
    def __repr__(self):
        return self.text

# Parse the PythonQL file and return a parse tree
def parsePythonQL( s ):
  # Set up the lexer
  inputStream = InputStream(s)
  lexer = CustomLexer(inputStream)
  stream = CommonTokenStream(lexer)

  # Set up the error handling stuff
  error_handler = CustomErrorStrategy()
  error_listener = CustomErrorListener()
  buffered_errors = BufferedErrorListener()
  error_listener.addDelegatee(buffered_errors)

  # Set up the fast parser
  parser = PythonQLParser(stream)
  parser._interp.predictionMode = PredictionMode.SLL
  parser.removeErrorListeners()
  parser.errHandler = BailErrorStrategy()

  try:
    tree = parser.file_input()
    return (tree,parser)
  except:
    None

  lexer.reset()
  stream = CommonTokenStream(lexer)
  parser = PythonQLParser(stream)
  parser.errHandler = error_handler

  # Remove default terminal error listener & add our own
  parser.removeErrorListeners()
  parser.addErrorListener(error_listener)

  # Parse the input
  tree = parser.file_input()

  if error_listener.errors_encountered > 0:
    print(buffered_errors.buffer)
    raise Exception("Syntax error")

  return (tree,parser)

############################################################
# Some methods to test what kind of subtree we're dealing with
def isPathExpression(tree,parser):
    if isinstance(tree,TerminalNodeImpl):
        return False
    return (tree.getRuleIndex()==parser.RULE_test
                and len(tree.children)>1 )

def isTryExceptExpression(tree,parser):
    if isinstance(tree,TerminalNodeImpl):
        return False
    return (tree.getRuleIndex()==parser.RULE_try_catch_expr
                and len(tree.children)>1 )

def isTupleConstructor(tree,parser):
    if isinstance(tree,TerminalNodeImpl):
        return False

    if tree.getRuleIndex()==parser.RULE_testseq_query:
      if tree.children[0].getRuleIndex()==parser.RULE_test_as:
        if len(tree.children)>1:
          return True

    return False

def moreThanPythonComprehension(tree,parser):
  select_cl = tree.children[0]
  if len(select_cl.children)==2 or len(select_cl.children)==4:
    return True
  for cl in tree.children[1:]:
    if not cl.getRuleIndex() in [parser.RULE_for_clause, parser.RULE_where_clause]:
      return True
    if cl.getRuleIndex() == parser.RULE_where_clause:
      if cl.children[0].getText() == 'where':
        return True

  return False

def isQuery(tree,parser):
    if isinstance(tree,TerminalNodeImpl):
        return False

    if tree.getRuleIndex() in [parser.RULE_gen_query_expression,parser.RULE_list_query_expression]: 
        if len(tree.children)==2:
          return False
        if tree.children[1].getRuleIndex() in [parser.RULE_testlist_query,parser.RULE_testseq_query]:
          query = tree.children[1].children[0]
          if query.getRuleIndex() == parser.RULE_query_expression:
            return moreThanPythonComprehension(query,parser)
        return False

    if tree.getRuleIndex()==parser.RULE_set_query_expression:
        if len(tree.children)==2:
          return False

        dictorset = tree.children[1]
        if (dictorset.children[0].getRuleIndex() in [parser.RULE_query_map_expression,parser.RULE_query_expression]):
          return moreThanPythonComprehension(dictorset.children[0],parser)

        return False

    return False

def isChildStep(tree,parser):
    return (tree.getRuleIndex()==parser.RULE_path_step 
               and tree.children[0].getRuleIndex()==parser.RULE_child_path_step)

def isDescStep(tree,parser):
    return (tree.getRuleIndex()==parser.RULE_path_step and 
               tree.children[0].getRuleIndex()==parser.RULE_desc_path_step)

def isPredStep(tree,parser):
    return (tree.getRuleIndex()==parser.RULE_path_step and 
               tree.children[0].getRuleIndex()==parser.RULE_pred_path_step)

## Helper function to test the rule type (so we don't have to check
# terminal node all the time)
def ruleType(tree,t):
    if isinstance(tree,TerminalNodeImpl):
        return False
    return tree.getRuleIndex()==t

def tokType(tree,t):
    if isinstance(tree,TerminalNodeImpl):
        return tree.symbol.type==t
    elif len(tree.children)==1:
        return tokType(tree.children[0],t)
    return False

# Get the text of all terminals in the subtree
def getText(tree):
    if isinstance(tree,TerminalNodeImpl):
        return tree.getText()
    else:
        res = ""
        for c in tree.children:
            res += getText(c)
        return res

def getTextList(trees):
    return " ".join([getText(t) for t in trees])

def getTermsEsc(tree,parser):
    str = getTextList( get_all_terminals(tree,parser ) )
    str = str_encode(str)
    return '\"' + str + '\"'

# Get all top non-terminals from the tree of specific types
def getAllNodes(tree,rule_list):
  if isinstance(tree,TerminalNodeImpl):
    return []
  if tree.getRuleIndex() in rule_list:
    return [tree]
  else:
    return [x for c in tree.children for x in getAllNodes(c)]

# Create a token list out of a heterogenous list
def mk_tok(items):
    if isinstance(items,list):
        res = []
        for i in items:
            if isinstance(i,str):
                res.append(MyToken(i))
            elif isinstance(i,list):
                res += i
            else:
                res.append(i)
        return res
    else:
        return [MyToken(items)]

# Convert path expressions to Python
def get_path_expression_terminals(tree,parser):
    children = tree.children
    
    baseExpr = children[0]
    result = get_all_terminals(baseExpr,parser)
    
    for c in children[1:]:
        cond = mk_tok([ getTermsEsc(c.children[0].children[1],parser) ])
        if isChildStep(c,parser):
            result = mk_tok([ "PQChildPath", "(", result, ",", cond, ",", "locals", "(", ")", ")" ])
        else:
            result = mk_tok([ "PQDescPath", "(", result, ",", cond, ",", "locals", "(", ")", ")" ])
    
    return result

# Convert try-catch expression to Python
def get_try_except_expression_terminals(tree,parser):
    children = tree.children
    try_expr = children[1]
    except_expr = children[3]
 
    result = mk_tok(["PQTry", "(", getTermsEsc(try_expr,parser), ",",
               getTermsEsc(except_expr,parser), ",","locals()",")"])
    return result

# Convert the tuple constructor
def get_tuple_constructor_terminals(tree,parser):
    elements = [x for x in tree.children if not isinstance(x,TerminalNodeImpl)]
    res = []
    for e in elements:
      value = mk_tok([getTermsEsc(e.children[0],parser)])
      if len(e.children)==1:
        res.append(mk_tok(["(",value,",","None",")"]))
      else:
        alias = mk_tok([getTermsEsc(e.children[2],parser)])
        res.append(mk_tok(["(",value,",",alias,")"]))
    res = reduce(lambda x,y: x + mk_tok([","]) + y, res)
    return mk_tok(["make_pql_tuple","(", "[",res,"]",",","locals","(",")",")"])

# Process the select clause
def process_select_clause(tree,parser):
    res = []
    if tree.getRuleIndex() == parser.RULE_select_clause:
      e = tree.children[0]
      if isinstance(tree.children[0], TerminalNodeImpl):
        e = tree.children[1]

      value_toks = mk_tok([getTermsEsc(e,parser)])
      return mk_tok(["{",'"name":"select"', ",", '"expr"', ":", value_toks, "}"])

    else:
      k = tree.children[0]
      e = tree.children[2]
      if isinstance(tree.children[0], TerminalNodeImpl):
        k = tree.children[1]
        e = tree.children[3]

      key_toks = mk_tok([getTermsEsc(k,parser)])
      values_toks = mk_tok([getTermsEsc(e,parser)])
      return mk_tok(["{",'"name":"select"', ",", '"key"', ":", key_toks, ",", '"value"', ":", value_toks, "}" ])

# Process the for clause
def process_for_clause(tree,parser):
    clauses = [c for c in tree.children if ruleType(c,parser.RULE_for_clause_entry)]
    res = []
    for cl in clauses:
        variable = '"'+getText(cl.children[0])+'"'
        expression = getTermsEsc(cl.children[2],parser)
        clause_tokens =  mk_tok(["{", '"name":"for"', ",", '"var"', ":", variable, ",", '"expr"', ":", expression,"}"]) 
        res.append(clause_tokens)
    return res

# Process the let clause
def process_let_clause(tree,parser):
    clauses = [c for c in tree.children if ruleType(c,parser.RULE_let_clause_entry)]
    res = []
    for cl in clauses:
        variable = '"'+getText(cl.children[0])+'"'
        expression = getTermsEsc(cl.children[2],parser)
        clause_tokens =  mk_tok(["{", '"name":"let"', ",", '"var"', ":", variable, ",", '"expr"', ":", expression,"}"]) 
        res.append(clause_tokens)
    return res

# Process the order by clause
def process_orderby_clause(tree,parser):
    res = []
    orderlist = tree.children[2]
    elements = [el for el in orderlist.children if ruleType(el,parser.RULE_orderlist_el)]
    for e in elements:
        ascdesc = "asc" if len(e.children)==1 else getText(e.children[1])
        ascdesc = '"'+ascdesc+'"'
        res.append(mk_tok(["(", getTermsEsc(e.children[0],parser),",", ascdesc, ")"]))
    res = reduce(lambda x,y: x + mk_tok([","]) + y, res)
    return mk_tok(["{",'"name":"orderby"', "," '"orderby_list"', ":" , "[", res, "]", "}"])

# Process the group by clause
def process_groupby_clause(tree,parser):
    res = []
    groupby_list = tree.children[2]
    for e in [e for e in groupby_list.children if ruleType(e,parser.RULE_group_by_var)]:
        if len(e.children)==1 and tokType(e.children[0],parser.NAME):
          res.append(mk_tok(['"'+getText(e)+'"']))
        else:
          gby_expr = getTermsEsc(e.children[0],parser)
          alias = gby_expr
          if len(e.children)==3:
             alias = '"'+getText(e.children[2])+'"'
          res.append(mk_tok(["(", gby_expr, ",", alias, ")"]))
        
    res = reduce(lambda x,y: x + mk_tok([","]) + y, res)
    return mk_tok(["{",'"name":"groupby"', "," '"groupby_list"', ":", "[", res, "]", "}"])

def process_count_clause(tree,parser):
    return mk_tok(["{", '"name":"count"', ",", '"var"', ":", '"'+getText(tree.children[1])+'"', "}"])

# Process the where clause (this is easy)
def process_where_clause(tree,parser):
    return mk_tok(["{", '"name":"where"', ",", '"expr"', ":", getTermsEsc(tree.children[1],parser),"}"])

# Process the window clause (hairy stuff)
def get_window_vars(tree,parser,type):
  res = {}
  for c in tree.children:
    if c.getRuleIndex() == parser.RULE_current_item:
      res[type+"_curr"] = getText(c)
    if c.getRuleIndex() == parser.RULE_positional_var:
      res[type+"_at"] = getText(c.children[1])
    if c.getRuleIndex() == parser.RULE_previous_var:
      res[type+"_prev"] = getText(c.children[1])
    if c.getRuleIndex() == parser.RULE_next_var:
      res[type+"_next"] = getText(c.children[1])
  return res

def process_window_clause(tree,parser):
  window = tree.children[0]
  tumbling = window.getRuleIndex() == parser.RULE_tumbling_window
  window_var = getText(window.children[3])
  binding_seq = getTermsEsc(window.children[5],parser)
  start_vars = get_window_vars(window.children[6].children[1],parser,"s")
  start_cond = getTermsEsc(window.children[6].children[3],parser)
  end_vars = {}
  end_cond = None
  only = False
  if len(window.children)==8:
    end_vars = get_window_vars(window.children[7].children[2],parser,"e")
    end_cond = getTermsEsc(window.children[7].children[4],parser)
    if window.children[7].children[0].children:
      only = True

  start_vars.update( end_vars )
  var_tokens = [mk_tok([ '"'+k+'"', ":", '"'+start_vars[k]+'"' ]) for k in start_vars ]
  var_tokens = reduce(lambda x,y: x + mk_tok([","]) + y, var_tokens)

  return mk_tok([ "{", '"name":"window"', "," , '"tumbling"', ":", repr(tumbling), "," '"only"', ":", repr(only), ",",
			'"in"', ":", binding_seq, ",",
                        '"s_when"', ":", start_cond, ",",
                        mk_tok([ '"e_when"', ":", end_cond, ","]) if end_cond else [],
                        '"vars"', ":", "{", '"var"', ":", '"'+window_var+'"', ",", var_tokens, "}", "}" ])
                        
# Process the query. The query is turned into a function call
# PyQuery that takes all the clauses and evaluates them.

def get_query_terminals(tree,parser):
    query_type = None
    if tree.getRuleIndex() == parser.RULE_gen_query_expression:
      query_type = "gen"

    elif tree.getRuleIndex() == parser.RULE_list_query_expression:
      query_type = "list"

    elif tree.getRuleIndex() == parser.RULE_set_query_expression:
      if tree.children[1].children[0].getRuleIndex() == parser.RULE_query_expression:
        query_type = "set"
      else:
        query_type = "map"

    query_expr = tree.children[1].children[0]
    children = query_expr.children
    clauses = []

    # We process select clause separately, because we add it
    # to the end of the list

    select_clause = process_select_clause(children[0], parser)
    for c in children[1:]:
      if c.getRuleIndex() == parser.RULE_for_clause:
        clauses += process_for_clause(c, parser)
      elif c.getRuleIndex() == parser.RULE_let_clause:
        clauses += process_let_clause(c, parser)
      elif c.getRuleIndex() == parser.RULE_where_clause:
        clauses.append( process_where_clause(c, parser) )
      elif c.getRuleIndex() == parser.RULE_count_clause:
        clauses.append( process_count_clause(c, parser) )
      elif c.getRuleIndex() == parser.RULE_group_by_clause:
        clauses.append( process_groupby_clause(c, parser) )
      elif c.getRuleIndex() == parser.RULE_order_by_clause:
        clauses.append( process_orderby_clause(c, parser) )
      elif c.getRuleIndex() == parser.RULE_window_clause:
        clauses.append( process_window_clause(c, parser) )
      else: 
        raise Exception("Unknown clause encountered")

    # Add the select clause at the end
    clauses.append( select_clause )

    clauses_repr = reduce( lambda x,y: x + mk_tok([","]) + y, clauses)
    return mk_tok(["PyQuery", "(", "[", clauses_repr, "]", ",", "locals", "(", ")", ",", '"'+query_type+'"', ")"])

# Process an arbitrary PythonQL program
def get_all_terminals(tree,parser):
    if isinstance(tree,TerminalNodeImpl):
        return [tree]
    if isPathExpression(tree,parser):
        return get_path_expression_terminals(tree,parser)
    elif isTryExceptExpression(tree,parser):
        return get_try_except_expression_terminals(tree,parser)
    elif isTupleConstructor(tree,parser):
        return get_tuple_constructor_terminals(tree,parser)
    elif isQuery(tree,parser):
        return get_query_terminals(tree,parser)
    else:
        children = []
        if tree.children:
            children = reduce( lambda x,y: x+y, [get_all_terminals(c,parser) for c in tree.children])
        return children

####################################
#The rest of the code creates a Python program out of PythonQL, which can be run with Python3 interpreter
####################################

def makeIndent(i):
    return "  "*(2*i)

def all_ws(t):
    return all([x==' ' for x in t])

# Generate a program from a list of text tokens
def makeProgramFromTextTokens(tokens):
    result = ""
    indent = 0
    buffer = ""
    for t in tokens:
        if buffer!="":
            if t==' ' or t=='  ' or t=='\n' or t=='\n ' or t=='\r\n':
                result += buffer + '\n'
                buffer = ""
            else:
                buffer += t + " "
        else:
            if t==' ':
                indent = indent -1
            elif '\n' in t or '\r' in t:
                indent -= 1
                indent = indent if indent>=0 else 0
            elif all_ws(t):
                indent = len(t)//2
            else:
                buffer = makeIndent(indent)
                buffer += t + " "
    return result

# Generate a program from a parse tree
def makeProgramFromFile(fname):
  str = "".join( open(fname).readlines() )
  return makeProgramFromString(str)

def makeProgramFromString(str):
  (tree,parser) = parsePythonQL(str)
  all_terminals = get_all_terminals(tree,parser)
  text_tokens = [t.getText() for t in all_terminals]
  return makeProgramFromTextTokens(text_tokens)
