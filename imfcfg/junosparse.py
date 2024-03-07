#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, subprocess, re, struct
import ply.lex as lex, ply.yacc as yacc


class JunosLexer(object):
    states = (
        ("blockcomment", "exclusive"),
        ("str", "exclusive"),
    )
    tokens = []
    keywords = []

    # tokens += list([x.upper() for x in keywords])

    tokens += ["WORD", "SPACE"]
    t_ignore = ""
    literals = "{}"

    def t_ANY_error(self, t):
        def indstr(line, pos):
            return "".join([" " if i != "\t" else "\t" for i in line[:pos]])

        ldata = t.lexer.lexdata
        line_start = ldata.rfind("\n", 0, t.lexpos) + 1
        line = ldata[line_start:].split("\n", 1)[0]
        relpos = t.lexpos - line_start

        raise ValueError(
            "<input>:%d:%d: Illegal character '%s'\n> %s\n> %s^- here"
            % (t.lexer.lineno, relpos + 1, t.value[0], line, indstr(line, relpos))
        )

    def t_space(self, t):
        r"\s+"
        t.lexer.lineno += t.value.count("\n")
        t.type = "SPACE"
        return t

    def t_word(self, t):
        r'[^\s{}"/]+'
        t.type = "WORD"
        return t

    def t_slash(self, t):
        r"/(?=[^/])"
        t.type = "WORD"
        return t

    # string handling
    t_str_ignore = ""

    def t_strbegin(self, t):
        r'"'
        t.lexer.push_state("str")
        t.lexer.raw_text = '"'

    def t_str_end(self, t):
        r'"'
        t.lexer.pop_state()
        t.type = "WORD"
        t.value = t.lexer.raw_text + '"'
        return t

    def t_str_other(self, t):
        r'[^\\"]+'
        t.lexer.raw_text += t.value
        t.lexer.lineno += t.value.count("\n")

    def t_str_bsl(self, t):
        r"\\."
        t.lexer.raw_text += t.value

    # comment handling
    t_blockcomment_ignore = ""

    def t_blockcommentbegin(self, t):
        r"/\*"
        t.lexer.push_state("blockcomment")
        t.lexer.comment_text = t.value

    def t_blockcomment_end(self, t):
        r"\*/"
        t.lexer.comment_text += t.value
        t.lexer.pop_state()

        t.value = t.lexer.comment_text
        t.type = "SPACE"
        return t

    # def t_blockcomment_newline(self, t):
    #    r'\n+'
    #    self.new_line(t.lexer, len(t.value))
    #    t.lexer.comment_text += t.value
    def t_blockcomment_other(self, t):
        r"[^\*]+"
        t.lexer.comment_text += t.value
        t.lexer.lineno += t.value.count("\n")

    def t_blockcomment_star(self, t):
        r"[\*]+(?=[^/])"
        t.lexer.comment_text += t.value

    # general foo
    def build(self, **kwargs):
        self.lexer = lex.lex(module=self, optimize=1, lextab="ply_lex", **kwargs)
        return self

    def test(self, data):
        self.lexer.input(data)
        while True:
            tok = self.lexer.token()
            if not tok:
                break
            print(tok)


class Blob(dict):
    def __init__(self, value=""):
        super(Blob, self).__init__()
        self.value = value


class JunosParser(object):
    tokens = JunosLexer.tokens

    def p_data_empty(self, p):
        """data :"""
        p[0] = Blob()

    def p_data(self, p):
        """data : WORD data
        | SPACE data"""
        p[0] = p[2]
        p[0].value = p[1] + p[0].value

    def p_blob(self, p):
        """data : WORD SPACE '{' data '}' data"""
        p[0] = p[6]
        p[0].value = p[1] + p[2] + "{" + p[4].value + "}" + p[0].value
        p[0][p[1]] = p[4]

    def build(self, **kwargs):
        self.parser = yacc.yacc(
            module=self, start="data", tabmodule="ply_yacc", **kwargs
        )
        return self


lexer = JunosLexer().build()
parser = JunosParser().build()


def parse(data):
    lexer.lexer.lineno = 1
    return parser.parser.parse(data, lexer=lexer.lexer)


if __name__ == "__main__":
    tdata = open(sys.argv[1], "r").read()
    lexer.test(tdata)
    data = parse(tdata)

    def recur(data, indent):
        for k, v in data.items():
            print('%s"%s": %d bytes' % ("  " * indent, k, len(v.value)))
            recur(v, indent + 1)

    print("root: %d bytes" % (len(data.value)))
    recur(data, 1)
