# tinyssb/__init__.py

__all__ = [
    'erase_all',
    'list_identities',
    'generate_id',
    'load_identity'
]

import json
import os

import bipf
from . import packet, keystore, identity, util, repository, io, node
from .dbg import dbg, GRE

def erase_all():
    """
    Delete all data on the file system.
    :return: None
    """
    os.system("rm -rf data")

def list_identities():
    """
    List identities that are on the data folder.
    Use case: different people use the same computer.
    To do: add security checks
    :return: an array of strings
    """
    return os.listdir(util.DATA_FOLDER)

def generate_id(peer_name):
    """
    Create new peer (delete data if existing).
    Stores the data on the file system, make generic log, create default sub-feeds and
    add udp_multicast as interface and start it (listen/read loops).
    Only trusted peer is self
    :param peer_name: string
    :return: an instance of Node
    """
    pfx = util.DATA_FOLDER + peer_name
    ks = keystore.Keystore()
    pk = ks.new(peer_name)

    os.system(f"mkdir -p {pfx}/_blob")
    os.system(f"mkdir -p {pfx}/_logs")
    os.system(f"mkdir -p {pfx}/_backed")
    with open(f"{pfx}/_backed/config.json", "w") as f:
        f.write(util.json_pp({'name': peer_name, 'rootFeedID': util.hex(pk)}))

    repo = repository.REPO(pfx, lambda feed_id, msg, sig: ks.verify(feed_id, msg, sig))
    repo.mk_generic_log(pk, packet.PKTTYPE_plain48, b'log entry 1', lambda msg: ks.sign(pk, msg))
    root = __start_node(repo, ks, pk)

    default = {}
    for n in ['aliases', 'public', 'apps']:
        fid = root.ks.new(n)
        name = bipf.dumps(n)
        name += bytes(16 - len(name))
        root.repo.mk_child_log(root.me, root.ks.get_signFct(root.me), fid,
                               root.ks.get_signFct(fid), name)
        default[n] = fid
    dbg(GRE, f"Create identity \"{peer_name}\"")
    return identity.Identity(root, peer_name, default)

def load_identity(peer_name):
    """
    Launch a peer whose data is stored locally
    :param peer_name: the name of the folder
    :return: instance of node
    """
    pfx = util.DATA_FOLDER + peer_name
    with open(pfx + '/_backed/config.json') as f:
        cfg = json.load(f)
    me = util.fromhex(cfg['rootFeedID'])
    ks = keystore.Keystore()
    ks.load(pfx + '/_backed/' + cfg['rootFeedID'])

    repo = repository.REPO(pfx, lambda feed_id, sig, msg: ks.verify(feed_id, sig, msg))
    root = __start_node(repo, ks, me)
    log = root.repo.get_log(me)
    default = {}
    for i in range(len(log) + 1):
        pkt = log[i]
        if pkt.typ[0] == packet.PKTTYPE_mkchild:
            fid = pkt.payload[:32]
            log_name = bipf.loads(pkt.payload[32:])
            default[log_name] = fid
    return identity.Identity(root, peer_name, default)

def __start_node(repo, ks, me):
    faces = [io.UDP_MULTICAST(('224.1.1.1', 5000))]
    nd = node.NODE(faces, ks, repo, me)
    return nd
