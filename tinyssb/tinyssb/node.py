#

# tinyssb/node.py   -- node (peering and replication) behavior
# 2022-04-09 <christian.tschudin@unibas.ch>


import hashlib
import _thread

from . import io, packet, util
from .dbg import *
from .exception import TinyException

LOGTYPE_private = 0x00  # private fid (not to be shared)
LOGTYPE_public  = 0x01  # public fid to synchronise with peers
LOGTYPE_remote  = 0x02  # public fid from a remote peer


class NODE:  # a node in the tinySSB forwarding fabric

    def __init__(self, faces, keystore, repo, me):
        self.faces = faces
        self.ks = keystore
        self.repo  = repo
        self.dmxt  = {}    # DMX  ~ dmx_tuple  DMX filter bank
        self.blbt  = {}    # hptr ~ blob_obj  blob filter bank
        self.logs = { util.hex(me): LOGTYPE_private }
        self.timers = []
        self.comm = {}
        #
        self.me = me
        self.pending_chains = []
        self.next_timeout = [0]
        self.ndlock = _thread.allocate_lock()

    def activate_log(self, fid, log_type):
        """
        Keeps track of all the active private, public and remote feeds
        """
        hex_fid = util.hex(fid)
        if log_type not in [LOGTYPE_private, LOGTYPE_public, LOGTYPE_remote]:
            raise TinyException(f"'{log_type}' is not a log type")
        self.ndlock.acquire()
        self.logs[hex_fid] = log_type
        self.ndlock.release()
        if log_type == LOGTYPE_remote:
            # If it doesn't exist, allocate space for the remote log
            log = self.repo.get_log(fid)
            if log is not None:
                self.request_latest(log, "Add new log")
                # log = self.repo.allocate_log(fid, 0, fid[:20])

    def deactivate_log(self, fid):
        hex_fid = util.hex(fid)
        try:
            self.ndlock.acquire()
            self.logs.pop(hex_fid)
            del self.repo.open_logs[fid]
            self.ndlock.release()
        except KeyError:
            self.ndlock.release()
            # dbg(YEL, f"Deactivate log: there is no log with id = {hex_fid}")

    def start(self):
        self.ioloop = io.IOLOOP(self.faces, self.on_rx)
        # dbg(TERM_NORM, '  starting thread with IO loop')
        _thread.start_new_thread(self.ioloop.run, tuple())
        # dbg(TERM_NORM, "  starting thread with arq loop")
        _thread.start_new_thread(self.arq_loop, tuple())

    def arm_dmx(self, dmx, fct=None, comment=None):
        """
        Add or delete a dmx entry.

        Call with a lambda function to prepare for the next message
        for this feed, without function to delete the entry when the
        message has been received
        :param dmx: demultiplexing field, 7 bytes
        :param fct: function to call when the packet arrives
        :param comment: description comment
        :return: nothing
        """
        if fct == None:
            if dmx in self.dmxt: del self.dmxt[dmx]
            if dmx in self.comm: del self.comm[dmx]
        else:
            # print(f"+dmx {util.hex(dmx)} / {comment}")
            self.dmxt[dmx] = fct
            self.comm[dmx] = comment

    def arm_blob(self, hptr, fct=None):
        """
        See arm_dmx
        """
        if not fct:
            if hptr in self.blbt: del self.blbt[hptr]
        else:
            self.blbt[hptr] = fct

    def on_rx(self, buf, neigh):
        """
        Manages the reception from all interfaces
        :param buf: the message
        :param neigh: Interfaces available (added in IOLOOP.run)
        :return: nothing
        """
        # all tSSB packet reception logic goes here!
        # dbg(GRE, "<< buf", len(buf), util.hex(buf[:20]), "...")
        # if len(buf) == 120:
            # try: dbg(RED, "<< is", bipf.loads(buf[8:56]))#, "...", buf[:7] in self.dmxt)
            # except: pass

        dmx = buf[:7]
        if dmx in self.dmxt:
            self.dmxt[dmx](buf, neigh)
        else:
            hptr = hashlib.sha256(buf).digest()[:20]
            if hptr in self.blbt:
                self.blbt[hptr](buf, neigh)

    def push(self, pkt_lst, forced=True):
        for pkt in pkt_lst:
            feed = self.repo.get_log(pkt.fid)
            if feed == None: continue
            if not forced and feed.subscription <= 0: continue
            for f in self.faces:
                # print(f"_ enqueue {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
                f.enqueue(pkt.wire)
            feed.subscription = 0

    def write_plain_48B(self, fid, buf48, sign=None):
        self.write_typed_48B(fid, buf48, packet.PKTTYPE_plain48, sign)

    def write_typed_48B(self, fid, buf48, typ, sign=None):
        """
        Prepare next log entry, finalise this packet and send it.
        :param fid: feed id (bin encoded)
        :param typ: signature algorithm and packet type
        :param buf48: payload (will be padded)
        :param sign: signing function
        :return: nothing
        """
        feed = self.repo.get_log(fid)
        self.ndlock.acquire()
        if sign is None:
            pkt = feed.write_typed_48B(buf48, typ, lambda msg: self.ks.sign(fid, msg))
        else:
            pkt = feed.write_typed_48B(buf48, typ, sign)
        self.arm_dmx(pkt.dmx) # remove potential old demux handler
        # dbg(GRE, f"DMX OUT: {util.hex(pkt.dmx)} for {util.hex(fid)}")
        self.ndlock.release()

        if self.logs[util.hex(fid)] == LOGTYPE_private: return

        for f in self.faces:
            # print(f"_ enqueue2 {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
            f.enqueue(pkt.wire)

    def write_blob_chain(self, fid, buf, sign=None):
        feed = self.repo.get_log(fid)
        self.ndlock.acquire()
        if sign is None:
            pkt, blobs = feed.prepare_chain(buf, lambda msg: self.ks.sign(fid, msg))
        else:
            pkt, blobs = feed.prepare_chain(buf, sign)
        buffer = self.repo.persist_chain(pkt, blobs)[:1]
        self.ndlock.release()

        if self.logs[util.hex(fid)] == LOGTYPE_private: return

        for f in self.faces:
            for p in buffer:
                # dbg(BLU, f"f={f}, pkt={p[:3]}")
                f.enqueue(p)

    # ----------------------------------------------------------------------

    def incoming_want_request(self, demx, buf, neigh):
        """
        Handle want request.

        Called from on_rx, added to self.dmxt in arm_dmx (from arq_loop)
        :param demx: DMX field of excpected packet
        :param buf: packet "as on the wire"
        :param neigh: the corresponding IO interface
        :return: nothing
        """
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # returns None, which means we can discard it
        if buf is None:
            return None
        buf = buf[7:]  # cut the DMX away
        while len(buf) >= 24:
            fid = buf[:32]
            seq = int.from_bytes(buf[32:36], 'big')
            h = util.hex(fid)[:20]  # idea: seq -= h?
            feed = None
            try:
                feed = self.repo.get_log(fid)
                if feed != None:
                    pkt = feed[seq]
                    # print(f"_ enqueue3 {util.hex(pkt.fid[:20])}.{pkt.seq} @{pkt.wire[:7].hex()}")
                    neigh.face.enqueue(pkt.wire)
                    # dbg(GRA, f'    have {h}.[{seq}], will send {x.hex()[:10]}')
            except:
                # dbg(GRA, f"    no entry for {h}.[{seq}]")
                if feed != None and seq == len(feed) + 1:
                    feed.subscription += 1
                pass
            buf = buf[36:]

    def incoming_blob_request(self, demx, buf, neigh):
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # returns None, which means we can discard it
        if buf is None:
            return None
        buf = buf[7:]  # cut DMX off
        while len(buf) >= 22:
            hptr = buf[:20]
            # Take the first 3 bytes of the header: the last of the chain is only 0s (whole header)
            # FIXME : compute count on each iteration?
            cnt = int.from_bytes(buf[20:22], 'big')
            try:
                while cnt > 0:
                    blob = self.repo.fetch_blob(hptr)
                    if not blob:
                        break
                    # dbg(GRA, f'    blob {util.hex(hptr)}, will send')
                    neigh.face.enqueue(blob)
                    cnt -= 1
                    hptr = blob[-20:]
            except Exception as e:
                dbg(RED, e)
                # dbg(GRA, f"    no entry for {h}.[{seq}]")
                pass
            buf = buf[22:]

    def incoming_logentry(self, d, feed, buf, n):
        # Little perk for identity.__save_dmxt: calling with an empty buffer
        # return the feed id that we need to store to recreate the lambda
        if buf is None:
            return feed.fid
        pkt = feed.append(buf)  # this invokes the callback
        self.ndlock.acquire()
        if pkt == None:
            self.ndlock.release()
            return
        assert pkt.fid == feed.fid
        oldfeed = feed
        if not pkt:
            dbg(RED, "    verification failed")
            self.ndlock.release()
            return
        # dbg(GRE, f'  added {pkt.fid.hex()[:20]}:{pkt.seq} {pkt.typ}')
        self.arm_dmx(d)  # remove current DMX handler, request was satisfied
        # FIXME: instead of eager blob request, make this policy-dependent
        if pkt.typ[0] == packet.PKTTYPE_contdas:  # switch feed
            dbg(GRA, f'  told to stop old feed {util.hex(pkt.fid)[:20]}../{pkt.seq}')
            # FIXME: security checks (can this feed still be continued etc)
            newFID = pkt.payload[:32]
            # Redundant with session._process() in callback for instances, do nothing
            feed = self.repo.allocate_log(newFID, 0, newFID[:20])  # install cont.
            if feed is None:
                feed = self.repo.get_log(newFID)
            dbg(GRA, f'  ... and to switch to new feed {util.hex(newFID)[:20]}..')
            # feed.subscription += 1
            # feed.set_append_cb(oldfeed.acb)
            # oldfeed = None
        elif pkt.typ[0] == packet.PKTTYPE_mkchild:
            dbg(GRE, f'  told to create subfeed for {util.hex(pkt.fid)[:20]}../{pkt.seq}')
            # FIXME: security checks (can this feed still be continued etc)
            newFID = pkt.payload[:32]
            newFeed = self.repo.allocate_log(newFID, 0, newFID[:20])  # install cont.
            dbg(GRE, f'    new child is {util.hex(newFID)[:20]}..')
            newFeed.set_append_cb(oldfeed.acb)
            pktdmx = packet._dmx(newFID + int(1).to_bytes(4, 'big') + newFID[:20])
            # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(newFID)[:20]}.[1] /mkchild")
            self.arm_dmx(pktdmx,
                         lambda buf, n: self.incoming_logentry(pktdmx,
                                                               newFeed, buf, n),
                         f"{util.hex(newFID)[:20]}.[1] /mkchild")
            self.request_latest(newFeed, "<<~")
        elif pkt.typ[0] == packet.PKTTYPE_chain20:  # prepare for first blob in chain:
            h = util.hex(feed.fid)[:20]
            # FIXME where is the node ('nd') defined? It throws errors
            pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
            self.request_chain(pkt)
        # elif pkt.typ[0] == packet.PKTTYPE_iscontn:
        #     if pkt.seq == 1: # first packet has proof, don't invoke the cb
        #         oldfeed = None
        seq, prevhash = feed.getfront()
        seq += 1
        nextseq = seq.to_bytes(4, 'big')
        pktdmx = packet._dmx(feed.fid + nextseq + prevhash)
        # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(feed.fid)[:20]}.[{seq}] /incoming")
        self.arm_dmx(pktdmx,
                     lambda buf, n: self.incoming_logentry(pktdmx,
                                                           feed, buf, n),
                     f"{util.hex(feed.fid)[:20]}.[{seq}] /incoming")
        # set timeout to 1sec more than production interval
        self.next_timeout[0] = time.time() + 6
        self.ndlock.release()

    def incoming_chainedblob(self, cnt, h, buf, n):
        if len(buf) != 120: return
        # dbg(GRA, f"RCV blob@dmx={util.hex(h)} / chained")
        self.arm_blob(h)  # remove current blob handler, expected blob was received
        self.repo.add_blob(buf)
        hptr = buf[-20:]
        if hptr != bytes(20):
            # rearm a blob handler for the next blob in the chain:
            # dbg(GRA, f"    awaiting next blob {util.hex(hptr)}")
            cnt -= 1
            if cnt == 0:  # aks for next batch of blob
                d = packet._dmx(b'blobs')
                wire = d + hptr + int(4).to_bytes(2, 'big')
                for f in self.faces:
                    f.enqueue(wire)
                    # dbg(GRA, f"SND blob chain request to dmx={d.hex()} for {hptr.hex()}")
                cnt = 4
            self.arm_blob(hptr,
                          lambda buf, n: self.incoming_chainedblob(cnt, hptr, buf, n))
        else:
            # dbg(GRA, f"    end of chain was reached")
            pass

    def request_latest(self, feed, comment="?"):
        """
        request the latest packet for a given feed
        :param feed: instance of LOG
        :param comment: Optional comment to be included in the request
        :return: nothing
        """
        if self.logs.get(util.hex(feed.fid)) is None:
            dbg(GRE, "Oh shit")
        if self.logs.get(util.hex(feed.fid)) != LOGTYPE_remote:
            # if len(self.my_logs.intersection(feed.fid)) == 0:
            return
        # dbg(GRE, f"in request latest for {comment}: !!!!!!!!!!{self.logs.get(util.hex(feed.fid))}")

        seq, prevhash = feed.getfront()
        seq += 1
        nextseq = seq.to_bytes(4, 'big')
        pktdmx = packet._dmx(feed.fid + nextseq + prevhash)
        # dbg(GRA, f"+dmx pkt@{util.hex(pktdmx)} for {util.hex(feed.fid)[:20]}.[{seq}]")
        # dbg(RED, f"{comment} for {util.hex(feed.fid)[:20]}.[{seq}]")
        self.arm_dmx(pktdmx,
                     lambda buf, n: self.incoming_logentry(pktdmx,
                                                           feed, buf, n),
                     comment + f"{util.hex(feed.fid)[:20]}.[{seq}])")

        for p in self.logs:
            p = util.fromhex(p)
            want_dmx = packet._dmx(p + b'want')
            wire = want_dmx + feed.fid + nextseq
            # does not need padding to 120B, it's not a log entry or blob
            d = util.hex(want_dmx)
            h = util.hex(feed.fid)[:20]
            for f in self.faces:
                f.enqueue(wire)
                # dbg(GRA, f"SND {len(wire)} want request to dmx={d} for {h}.[{seq}]")

    def request_chain(self, pkt):
        # dbg(YEL, "request_chain", util.hex(pkt.fid)[:8], pkt.seq,
        #       util.hex(pkt.chain_nextptr) if pkt.chain_nextptr else None)
        hptr = pkt.chain_nextptr
        if hptr == None: return
        # dbg(GRA, f"+blob @{util.hex(hptr)}")
        self.arm_blob(hptr,
                      lambda buf, n: self.incoming_chainedblob(4, hptr, buf, n))
        d = packet._dmx(b'blobs')
        wire = d + hptr + int(4).to_bytes(2, 'big')
        for f in self.faces:
            f.enqueue(wire)
            # dbg(GRA, f"SND blob chain request to dmx={d.hex()} for {hptr.hex()}")

    def arq_loop(self):  # Automatic Repeat reQuest
        # dbg(GRA, f"This is Replication for node {util.hex(self.myFeed.fid)[:20]}")
        # prepare to serve incoming requests for logs I have
        # i.e., sent to me, which means with DMX="myFID want"

        # dbg(GRA, f"+dmx want@{util.hex(want_dmx)} / me {util.hex(self.me)[:20]}...")
        for fid in self.logs:
            if self.logs[fid] != LOGTYPE_remote:
                want_dmx = packet._dmx(util.fromhex(fid) + b'want')
                self.arm_dmx(want_dmx,
                     lambda buf, n: self.incoming_want_request(want_dmx, buf, n), f"arq to me {fid[:20]}")

        # prepare to serve blob requests
        blob_dmx = packet._dmx(b'blobs')
        # dbg(GRA, f"+dmx blob@{util.hex(blob_dmx)}")
        self.arm_dmx(blob_dmx,
                     lambda buf, n: self.incoming_blob_request(blob_dmx, buf, n), "init blobs")
        while True:  # periodic ARQ
            now = time.time()
            if self.next_timeout[0] < now:
                self.ndlock.acquire()
                for fid in self.logs:
                    feed = self.repo.get_log(util.fromhex(fid))
                    if self.logs[fid] != LOGTYPE_remote or feed is None:
                        continue
                    if feed[-1].typ[0] == packet.PKTTYPE_contdas:
                        # this is a terminated feed, don't ask for news
                        continue
                    self.request_latest(feed, "arq for logs")
                self.ndlock.release()

                rm = []
                for pkt in self.pending_chains:
                    pkt.undo_chain(lambda h: self.repo.fetch_blob(h))
                    if pkt.content_is_complete():
                        rm.append(pkt)
                    else:  # FIXME: should have a max retry count
                        self.request_chain(pkt)
                for r in rm:
                    self.pending_chains.remove(pkt)
                self.next_timeout[0] = now + 1
                time.sleep(2)
            else:
                time.sleep(self.next_timeout[0] - now)

# eof
