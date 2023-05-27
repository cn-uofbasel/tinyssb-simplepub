#

# tinyssb/util.py
# 2022-04-09 <christian.tschudin@unibas.ch>

import base64
import sys

if sys.implementation.name == 'micropython':
    import binascii
    fromhex = binascii.unhexlify
    hex = lambda b: binascii.hexlify(b).decode()
else:
    fromhex = lambda h: bytes.fromhex(h)
    hex = lambda b: b.hex()

b64 = lambda b: base64.b64encode(b).decode()

DATA_FOLDER = './data/'

# wrote our own json.dumps ..
# because micropython's json.dumps() does not know how to pretty print
def json_pp(d, indent=''):
    # extended JSON (prints byte arrays as 0xHEXSEQUENCE)
    def stringify(v):
        if type(v) == bytes:
            return "0x" + v.hex()
        elif type(v) == str:
            return '"' + v + '"'
        return str(v)
    indent += '  '
    if d == None:      return "null"
    # if type(d) == int: return str(d)
    # if type(d) == str: return '"' + d + '"'
    if type(d) == list:
        jsonstr = '[\n'
        cnt = 1
        for i in d:
            jsonstr += indent + json_pp(i, indent)
            jsonstr += ',\n' if cnt < len(d) else  '\n'
            cnt += 1
        jsonstr += indent[:-2] + ']'
        return jsonstr
    if type(d).__name__ in ['dict', 'OrderedDict']:
        jsonstr = '{\n'
        cnt = 1
        for k,v in d.items():
            jsonstr += indent + stringify(k) + ': ' + json_pp(v, indent)
            jsonstr += ',\n' if cnt < len(d) else '\n'
            cnt += 1
        jsonstr += indent[:-2] + '}'
        return jsonstr
    return stringify(d)

# eof
