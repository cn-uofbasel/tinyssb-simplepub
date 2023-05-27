#

# tinyssb/session.py
# 2022-04-14 <christian.tschudin@unibas.ch>
import bipf
from . import packet, util, node
from .dbg import *
from .exception import UnexpectedPacketTinyException

class SlidingWindow:
    """
    This class manages the feeds for the active instance inside an app.
    """

    def __init__(self, app, manager, id_number, local_fid, callback):
        self.app = app
        self.manager = manager
        self.id_number = id_number
        self.local_feed = self.manager.get_log(local_fid)
        self.rfd = set()  # set of remote feeds, one per peer in the instance (minus me)
        self.pending_fid = None # pending feed (oldest unacked cont feed), test needed
        self.callback = callback
        self.started = False
        self.window_length = 3

    def add_remote(self, remote_fid):
        """ Add a remote peer to the instance and sync with it """
        if remote_fid is None:
            return
        rf = self.manager.get_log(remote_fid)
        if rf is None:
            raise Exception(f"SESS: remote feed {remote_fid.hex()} not found")
        rf.set_append_cb(self.on_incoming)
        self.rfd.add(rf)
        self.manager.activate_log(remote_fid, node.LOGTYPE_remote)

    def set_callback(self, callback):
        self.callback = callback
        for r in self.rfd:
            r.set_append_cb(callback)
        
    def write(self, buffer, typ=packet.PKTTYPE_plain48):
        """
        Write data in the local feed to be transmitted to remote peers
        :param buffer: byte array or string (will be converted with bipf) of arbitrary length
        :param typ: type of the packet
        :return: nothing
        """
        if len(self.local_feed) > self.window_length:
            if self.pending_fid is None:
                self.pending_fid = self.local_feed.fid
            self.local_feed = self.manager.create_continuation_log(self.local_feed.fid)
            self.app.update_inst(self.id_number, None, self.local_feed.fid)
        self.manager.write_in_log(self.local_feed.fid, buffer, typ)

    def on_incoming(self, pkt):
        # dbg(BLU, f"SESS: incoming {pkt.fid[:20].hex()}:{pkt.seq} {pkt.typ}")
        if self.started:
            self._process(pkt)
        else:
            dbg(MAG, "not started yet")

    def close(self):
        # TODO
        self.started = False
        pass

    def _process(self, pkt):
        # print("SESS _processing")
        if pkt.typ[0] == packet.PKTTYPE_contdas:
            # dbg(MAG, f"Continuation packet: {pkt.payload[:32]} + {pkt.typ} + {pkt.fid}")
            self.app._update_inst_with_old_remote(self.id_number, pkt.payload[:32], pkt.fid)
            self.add_remote(pkt.payload[:32])
        elif pkt.typ[0] == packet.PKTTYPE_iscontn:
            # dbg(GRE, f" SESS: processing iscontn")
            # should verify proof
            oldFID = pkt.payload[:32]
            oldFeed = self.manager.get_log(oldFID)
            if not oldFeed.getfront()[0] == int.from_bytes(pkt.payload[32:36], "big"):
                dbg(RED, f"Continue feed: sequence number doesn't match:"
                         f" {oldFeed.getfront()[0]} vs {int.from_bytes(pkt.payload[32:36], 'big')}")
                return
            # FIXME one could check the hash too, but it is now computed on
            #  the last bytes of the signature which is not stored
            msg = oldFID # + ??
            self.write(msg, packet.PKTTYPE_acknldg)
        elif pkt.typ[0] == packet.PKTTYPE_acknldg:
            if self.manager.get_log_type(pkt.payload[:32]) == node.LOGTYPE_remote:
                return # Acknowledgement for a remote log
            if self.pending_fid is None:
                dbg(MAG, "no log to remove")
                return
            if self.manager.get_log(self.pending_fid) is None:
                dbg(MAG, "log already removed")
            dbg(GRA, f"SESS: removing feed {util.hex(self.pending_fid)[:20]}..")

            # self.manager.delete_one_log(self.pending_fid)
        elif pkt.typ[0] == packet.PKTTYPE_ischild:
            pass
        elif pkt.typ[0] == packet.PKTTYPE_mkchild:
            raise UnexpectedPacketTinyException("For now, instance feeds should not create sub feeds")
        elif pkt.typ[0] == packet.PKTTYPE_set or pkt.typ[0] == packet.PKTTYPE_delete:
            raise UnexpectedPacketTinyException("public feeds should not contain set or delete packets")
        else:
            # Blob or plain entries calls the callback set by the API
            if pkt.typ[0] == packet.PKTTYPE_chain20:
                # Blobs need an additional step to extract the data
                pkt.undo_chain(self.manager.get_blob_function())
            try:
                self.callback(pkt.payload, self.manager.get_contact_fid(pkt.fid), pkt, self.manager.get_log(pkt.fid))
            except IndexError as e:
                dbg(ERR, f"Error for {e}")

    def start(self):
        # does upcalls for all content received so far,
        # including acknowledging (and indirectly free) segments
        if self.started or len(self.rfd) == 0:
            return

        for remote_feed in self.rfd:
            i = 1
            while i <= len(remote_feed):
                pkt = remote_feed[i]
                self._process(pkt)
                if pkt.typ[0] == packet.PKTTYPE_contdas:
                    i = 1  # restart loop for continuation segment
                else:
                    i += 1
            remote_feed.set_append_cb(self.on_incoming)
            # dbg(RED, "sess has started (catchup done, switching to live processing)")
        self.started = True

    def replay(self, il, ir_list):
        for ir in ir_list:
            self.__replay(ir, False)
        self.__replay(il, True)

    def __replay(self, initial, me):
        if not self.started:
            self.start()
        f = self.manager.get_log(initial)
        i = 1
        while i <= len(f):
            pkt = f[i]
            if pkt.typ[0] == packet.PKTTYPE_contdas:
                f = self.manager.get_log(pkt.payload[:32])
                i = 1
            else:
                if pkt.typ[0] <= 1: # plain or chain
                    if pkt.typ[0] == packet.PKTTYPE_chain20:
                        pkt.undo_chain(self.manager.get_blob_function())
                    if me:
                        dbg(MAG, f"I sent \"{bipf.loads(pkt.get_content())}\"")
                    else:
                        dbg(RED, f"I received \"{bipf.loads(pkt.get_content())}\" "
                                 f"from {self.manager.get_contact_alias(self.manager.get_contact_fid(pkt.fid))} "
                                 f"(#{pkt.seq})")
                i += 1
# eof
