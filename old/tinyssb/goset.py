import hashlib
from collections import deque
from . import node, util #NODE, LOGTYPE_remote
import time

import functools


FID_LEN = 32
GOSET_DMX_STR = "tinySSB-0.1 GOset 1"
DMX_LEN = 7


class Claim:
    typ = b'c'
    lo = bytearray(0)  # FID_LEN
    hi = bytearray(0)  # FID_LEN
    xo = bytearray(0)  # FID_LEN
    sz = 0
    wire = bytearray(0)


class Novelty:
    typ = b'n'
    key = bytearray(FID_LEN)
    wire = bytearray(0)


NOVELTY_LEN = 33 # sizeof(struct novelty_s)
CLAIM_LEN = 98 # sizeof(struct claim_s)
ZAP_LEN = 33 # sizeof(struct zap_s)

GOSET_KEY_LEN   = FID_LEN
GOSET_MAX_KEYS  =    100
GOSET_ROUND_LEN = 10
MAX_PENDING     =     20
NOVELTY_PER_ROUND =    1
ASK_PER_ROUND   =      1
HELP_PER_ROUND  =      2
ZAP_ROUND_LEN   =   4500


class GOset():

    def __init__(self, node: node.NODE) -> None:
        self.node = node
        pass
    

    goset_dmx = hashlib.sha256(GOSET_DMX_STR.encode()).digest()[:DMX_LEN]

    state = bytearray(FID_LEN)
    keys = []
    pending_claims = []
    pending_novelty = deque()
    largest_claim_span = 0
    novelty_credit = 1

    def loop(self):
        while True:
            self.beacon()
            time.sleep(GOSET_ROUND_LEN)


    def rx (self, pkt: bytearray, aux: bytearray = None) -> None:
        
        
        if len(pkt) <= DMX_LEN:
            return
        
        buf = pkt[DMX_LEN:]
        print("rx Goset, len:", len(buf), chr(buf[0]))


        if len(buf) == NOVELTY_LEN and buf[0] == ord('n'):
            print("received Novelty")
            self._add_key(buf[1:NOVELTY_LEN])
            return
        
        if len(buf) != CLAIM_LEN or buf[0] != ord('c'):
            print("not claim")
            return
        
        cl = self.mkClaim_from_bytes(buf)

        if cl.sz > self.largest_claim_span:
            self.largest_claim_span = cl.sz
        if cl.sz == len(self.keys) and util.byteArrayCmp(self.state, cl.xo) == 0:
            print("GOset rx(): seems we are synced (with at least someone), |GOset|=", len(self.keys))
        else:
            self._add_key(cl.lo)
            self._add_key(cl.hi)
            self._add_pending_claim(cl)
            print("add pending claim")


    def beacon(self) -> None:
        if len(self.keys) == 0:
            return
        while(self.novelty_credit > 0 and len(self.pending_novelty) > 0):
            self.novelty_credit -= 1
            self._enqueue(self.pending_novelty.popleft().wire, self.goset_dmx, None)
        self.novelty_credit = NOVELTY_PER_ROUND
        cl = self.mkClaim(0, len(self.keys) - 1)
        if(util.byteArrayCmp(cl.xo, self.state) != 0):
            print("GOset state change to", cl.xo.hex(), "|keys|=", len(self.keys))
            self.state = cl.xo
            self.node.set_want_dmx(self.state)
        self._enqueue(cl.wire, self.goset_dmx, None)

        self.pending_claims.sort(key=lambda x: x.sz)
        max_ask = ASK_PER_ROUND
        max_help = HELP_PER_ROUND

        retain = []
        for c in self.pending_claims:
            if(c.sz == 0):
                return
            lo = next(i for i, x in enumerate(self.keys) if util.byteArrayCmp(x, c.lo) == 0)
            hi = next(i for i, x in enumerate(self.keys) if util.byteArrayCmp(x, c.hi) == 0)
            if lo == -1 or hi == -1 or lo > hi:
                continue
            partial = self.mkClaim(lo,hi)
            if(util.byteArrayCmp(partial.xo, c.xo) == 0):
                continue
            if partial.sz <= c.sz:
                if max_ask > 0:
                    self._enqueue(partial.wire, self.goset_dmx, None)
                    max_ask -= 1
                if partial.sz < c.sz:
                    retain.append(c)
                    continue

            if max_help > 0:
                max_help -= 1
                hi -= 1
                lo += 1
                if(hi <= lo):
                    self._enqueue(self.mkNovelty_from_key(self.keys[lo]).wire, self.goset_dmx, None)
                elif hi - lo <= 2:
                    self._enqueue(self.mkClaim(lo,hi).wire, self.goset_dmx, None)
                else:
                    sz = (hi + 1 -lo) // 2
                    self._enqueue(self.mkClaim(lo,lo+sz-1).wire, self.goset_dmx, None)
                    self._enqueue(self.mkClaim(lo+sz, hi).wire, self.goset_dmx, None)
                continue
            retain.append(c)
        
        while (len(retain) >= MAX_PENDING - 5):
            retain.removeLast()
        self.pending_claims = retain


    def _include_key(self, key: bytearray) -> None:
        zero = bytearray(GOSET_KEY_LEN)
        if key == zero:
            return False
        if key in self.keys:
            print("GOset _include_key(): key already exists")
            return False
        if len(self.keys) >= GOSET_MAX_KEYS:
            print("GOset _include_key(): too many keys")
            return False
        print("GOset _include_key", key)
        self.keys.append(key)
        return True
            

    def _add_key(self, key: bytearray) -> None:
        if (not self._include_key(key)): 
            return
        self.node.activate_log(key, node.LOGTYPE_remote)

        self.keys = sorted(self.keys, key=functools.cmp_to_key(util.byteArrayCmp))
        print("ADDKEY: ", self.keys)
        if len(self.keys) >= self.largest_claim_span:
            n = self.mkNovelty_from_key(key)
            if self.novelty_credit > 0:
                self._enqueue(n.wire, self.goset_dmx)
                self.novelty_credit -= 1
            elif len(self.pending_novelty) < MAX_PENDING:
                self.pending_novelty.append(n)
        print("GOSET _add_key(): added key", key)


    def _add_pending_claim(self, cl: Claim) -> None:
        for c in self.pending_claims:
            if c.sz == cl.sz and c.xo == cl.xo:
                return
        
        self.pending_claims.append(cl)
    

    def mkNovelty_from_key(self, key: bytes) -> Novelty:
        n = Novelty()
        n.wire = b'n' + key
        n.key = key
        return n
    

    def mkClaim_from_bytes(self, pkt: bytes) -> Claim:
        cl = Claim()
        cl.lo = pkt[1:33]
        cl.hi = pkt[33:65]
        cl.xo = pkt[65:97]
        cl.sz = pkt[97] # TODO maybe problems with unsigned integer
        cl.wire = pkt
        return cl
    

    def mkClaim(self, lo: int, hi: int) -> Claim:
        cl = Claim()
        cl.lo = self.keys[lo]
        cl.hi = self.keys[hi]
        cl.xo = self._xor(lo, hi)
        cl.sz = hi - lo + 1
        b = cl.sz.to_bytes() # TODO maybe problems with unsigned integer
        cl.wire = cl.typ + cl.lo + cl.hi + cl.xo + b
        return cl


    def _xor(self, lo: int, hi: int) -> bytearray:
        xor = bytearray(self.keys[lo])
        for k in self.keys[lo+1 : hi+1]:
            for i in range(len(xor)):
                xor[i] ^= k[i]
        return xor


    def _enqueue(self, buf: bytes, dmx: bytes = None, aux: bytes = None) -> None:
        pkt = buf if dmx == None else dmx + buf
        for f in self.node.faces:
            f.enqueue(pkt)

    
    def adjust_state(self) -> None:
        self.keys = sorted(self.keys, key=functools.cmp_to_key(util.byteArrayCmp))
        if (len(self.keys) > 0):
            cl = self.mkClaim(0, len(self.keys)-1)
            self.state = cl.xo
        else:
            self.state = bytearray(FID_LEN)
        print("GOset adjust_state() for", len(self.keys), "resulted in", self.state.hex())
        self.node.set_want_dmx(self.state)
