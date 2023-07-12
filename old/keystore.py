#!/usr/bin/env python3

# tinyssb/keystore.py
# 2022-04-09 <christian.tschudin@unibas.ch>
from collections import OrderedDict

import bipf
import pure25519
import util

# ----------------------------------------------------------------------

class Keystore:

    def __init__(self, cfg=None):
        if cfg is None:
            cfg = {}  # default arguments are evaluated only once, behaves as a global var
        self.kv = OrderedDict()
        for pk,d in cfg.items():
            self.kv[util.fromhex(pk)] = [util.fromhex(d['sk']), d['name']]

    def dump(self, fn):
        # write DB to BIPF file
        data = bipf.dumps(dict(self.kv))
        with open(fn, 'wb') as f:
            f.write(data)

    def load(self, fn):
        # read DB from BIPF file
        with open(fn, 'rb') as f:
            data = f.read()
        self.kv = bipf.loads(data)

    def new(self, nm=None):
        """
        Add a new feedID to the keystore without deleting others.

        The new key pair is unrelated to the other IDs.
        """
        sk, _ = pure25519.create_keypair()
        sk,pk = sk.sk_s[:32], sk.vk_s # just the bytes
        self.add(pk, sk, nm)
        return pk

    def add(self, pk, sk=None, nm=None):
        self.kv[pk] = [sk,nm]

    def remove(self, pk):
        del self.kv[pk]

    def sign(self, pk, msg):
        sk = pure25519.SigningKey(self.kv[pk][0])
        return sk.sign(msg)

    def get_signFct(self, pk):
        return mksignfct(self.kv[pk][0])

    def verify(self, pk, sig, msg):
        try:
            pure25519.VerifyingKey(pk).verify(sig,msg)
            return True
        except Exception as e:
            print(e)
            pass
        return False

    def __str__(self):
        out = OrderedDict()
        for pk,(sk,nm) in self.kv.items():
            out[util.hex(pk)] = { 'sk': util.hex(sk), 'name': nm }
        return util.json_pp(out)
        
def mksignfct(secret):
    def sign(m):
        sk = pure25519.SigningKey(secret)
        return sk.sign(m)
    return sign

def mkverifyfct(secret):
    def vfct(pk, s, msg):
        try:
            pure25519.VerifyingKey(pk).verify(s,msg)
            return True
        except Exception as e:
            print(e)
            pass
        return False
    return vfct

# eof
