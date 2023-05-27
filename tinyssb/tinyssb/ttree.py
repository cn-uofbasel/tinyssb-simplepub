#!/usr/bin/env python3

# tinyssb/ttree.py
# 2022-04-24 <christian.tschudin@unibas.ch>

# trust tree

class TrustTree():

    IS_ORPHANED = 0
    IS_SUB      = 1
    IS_CONT     = 2

    def __init__(self, rootFID):
        self.t = (rootFID, [], [], [])
        #                sub, cont, orph
        self.f2tuple = {rootFID: (self.IS_ORPHANED, self.t, rootFID)}

    def dump(self,fn):
        pass
    
    def load(self,fn):
        pass

    def mk_sub(self, fid1, fid2):
        t1 = self.f2tuple[fid1]
        print(t1)
        t1[1][1].append( fid2 )
        t2 = (fid2, [], [], [])
        print("  -->", t1)
        self.f2tuple[fid2] = (self.IS_SUB, t2, fid1)
        return t2

    def mk_cont(self, fid1, fid2):
        t1 = self.f2tuple[fid1]
        t2 = (fid2, [], [], [])
        t1[1][2].append( fid2 )
        self.f2tuple[fid2] = (self.IS_CONT, t2, fid1)
        return t2

    def get_ward(self, fid):
        t = self.f2tuple[fid]
        return t[2]

    def get_status(self, fid):
        t = self.f2tuple[fid]
        return t[0]

    def rm(self, fid):
        t = self.f2tuple[fid]
        if t[2] == fid: return  # can't remove root
        # successor node? else parent node?
        if len(t[1][2]) > 0:
            ward = self.f2tuple[t[1][2][0]][1]
        else:
            ward = self.f2tuple[t[2]][1]
        print("ward=", ward)
        # graft all subfeeds/cont/foster feeds to ward's foster entry
        for i in range(1,4):
            for f in t[1][i]:
                ward[3].append(f)
        # must remove ourselves, we could be sub or cont or foster
        for i in range(1,4):
            try:    ward[i].remove(ward[i].index(fid))
            except: pass
        del self.f2tuple[fid]


# ----------------------------------------------------------------------

if __name__ == '__main__':

    import json
    import os

    n = 'root'
    tt = TrustTree(n)

    n1 = 'n1'
    n11 = 'n11'
    n2 = 'n2'
    n25 = 'n25'
    n251 = 'n251'
    n25p = 'n25p'
    n25p1 = 'n25p1'
    n25p2 = 'n25p2'
    n25pp = 'n25pp'

    tt.mk_sub(n,    n1)
    tt.mk_sub(n1,   n11)
    tt.mk_sub(n,    n2)
    tt.mk_sub(n2,   n25)
    tt.mk_sub(n25,  n251)
    tt.mk_cont(n25,  n25p)
    tt.mk_cont(n25p, n25pp)
    tt.mk_sub(n25p, n25p1)
    tt.mk_sub(n25p, n25p2)

    def show():
        print(tt.t)
        print("\nnode parent predecessor:")
        for i in [n, n1, n11, n2, n25, n251, n25p, n25p1, n25p2, n25pp]:
            try:   print(i, tt.get_status(i), tt.get_ward(i))
            except KeyError: print(i, "... not in tt")

    show()

    # print(json.dumps(tt.f2tuple, indent=2))
    for k,v in tt.f2tuple.items():
        print(k, "=", v)
    # print(tt.f2tuple)
    print(n25pp in tt.f2tuple)
    tt.rm(n25p)
    show()

# eof
