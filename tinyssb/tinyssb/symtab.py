#!/usr/bin/env python3

# tinyssb/symtab.py  - a symbol table for replacing lengthy IDs by int values
# 2022-04-11 <christian.tschudin@unibas.ch>

import sys
if sys.implementation.name == 'micropython':
    import tinyssb.lopy4_cbor as cbor2
    import math
    def bitlen(x): return math.ceil(math.log2(x+1))
else:
    import cbor2
    def bitlen(x): return x.bit_length()


# from tinyssb import session
# from tinyssb.dbg import *

# algorithm textbooks implement symbol tables with binary search trees
# and often focus on adding a symbol but have no way of removing an entry.
# Here, we leverage Python's data structures and focus on
# functionality over (native) implementation speed.

SYMTAB_DEL = 0
SYMTAB_ADD = 1
SYMTAB_RSZ = 2

class SlidingWindowClient:

    def __init__(self, slw, port):
        self.slw = slw
        self.port = port
        self.slw.register(port, self)

    def upcall(self, buf48):
        pass

    def write(self, buf48):
        pass

    def __del__(self):
        self.slw.deregister(self.port)
        self.slf = None

    pass

class Symtab(SlidingWindowClient):

    def __init__(self, slidingWindowProvider, port):
        super().__init__(slidingWindowProvider, port)
        self.tbl = [None] * 16  # entries are [refcnt,cbor(val)]
        self.invtbl = {}
        self.cnt = 0
        self.bitmap = (1 << 16) - 1 # bit vector for empty slots
        # have a logical clock/timestamp?
        self.up = None # this is the "change notification callback"

    def __get__(self, a, ts=None):
        # returns the expanded value for abbreviation a
        if not a in self.tbl:
            raise IndexError
        return cbor2.loads(self.tbl[a][1])

    def set_upcall(self, upcall=None):
        self.up = upcall

    def upcall(self, buf48):
        lst = cbor2.loads(buf48)
        if lst[0] == SYMTAB_ADD:
            self._insert(lst[1], lst[2])
        elif lst[0] == SYMTAB_DEL:
            self._remove(lst[1])
        elif lst[0] == SYMTAB_RSZ:
            self._resize(lst[1])

    def _insert(self, pos, val):
        assert self.tbl[pos] == None
        self.bitmap ^= 1 << pos
        self.tbl[pos] = [1,val] # set refcnt to 1
        self.invtbl[val] = pos
        self.cnt += 1
        if self.up: self.up(['symbol added', cbor2.loads(val), pos])

    def _remove(self, pos):
        val = self.tbl[pos][1]
        self.tbl[pos] = None
        del self.invtbl[val]
        self.cnt -= 1
        self.bitmap |= 1 << pos
        if self.up: self.up(['symbol remvd', cbor2.loads(val), pos])

    def _resize(self, sz):
        while len(self.tbl) < sz:
            self.bitmap |= ((1<<16)-1) << len(self.tbl)
            self.tbl += [None] * 16

    def resolve(self, a):
        return self[a]

    def find(self, val):
        # like alloc(), but no allocation if not existing
        try: return self.invtbl[cbor2.loads(val)]
        except IndexError:
            raise

    def alloc(self, sym):
        # allocates a new shortcut for the given symbol,
        # (FIXME: also returns a timestamp?)

        sym_c = cbor2.dumps(sym) # encode symbol to also allow None as symbol
        try:
            a = self.invtbl[sym_c] # do we already know the symbol?
            self.tbl[a][0] += 1
            return a
        except:
            pass

        if (self.cnt == len(self.tbl)): # grow by 16 entries if full
            self.bitmap |= ((1<<16)-1) << len(self.tbl)
            self.tbl += [None] * 16
            self.slw.write_plain_48B(cbor2.dumps([SYMTAB_RSZ, len(self.tbl)]))

        # find lowest set bit
        a = bitlen(self.bitmap & ~(self.bitmap - 1)) - 1
        self._insert(a, sym_c)
        self.slw.write_plain_48B(cbor2.dumps([SYMTAB_ADD, a, sym_c]))
        return a

    def free(self, a, ts=None):
        # removes the mapping for symbol at position a if refcnt is below 2
        val = self.tbl[a]
        if val == None:
            raise IndexError
        if val[0] > 1:
            val[0] -= 1
            return
        self._remove(a)
        self.slw.write_plain_48B(cbor2.dumps([SYMTAB_DEL, a]))

        if len(self.tbl) - self.cnt > 32: # shrink tbl
            i = bitlen(self.bitmap)   # highest free entry, position
            j = self.bitmap ^ ((1 << i)-1) # vector with highest busy entry
            if i - bitlen(j) > 16:
                self.tbl = self.tbl[:-16]
                self.bitmap &= (1 << len(self.tbl)) - 1

    def sync(self, ts=None):
        # signal that no earlier timestamps have to be served anymore
        # and that fresh lookups will be made for everything
        return None

# ----------------------------------------------------------------------

if __name__ == '__main__':

    import os

    # test whether shrinking works:

    symtab = Symtab()
    for i in range(75):
        val = os.urandom(1)
        a = symtab.alloc(val)

    for n in range(30):
        for i in range(10):
            val = os.urandom(1)
            symtab.alloc(val)
        cnt = 0
        while cnt < 10:
            try:
                i = os.urandom(1)[0] % len(symtab.tbl)
                symtab.free(i)
                cnt += 1
            except Exception as e:
                pass
        print('-', len(symtab.tbl), symtab.cnt, len(symtab.tbl) - symtab.cnt, "free")
       
# eof
