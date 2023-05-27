import bipf
import tinyssb as tiny
from demo_app import *
from tinyssb import util
from tinyssb.dbg import *

# randomly chosen ID for my app
APP_ID = util.fromhex("6a7599019df4b5bf09781b6a3653946c278a5cdc236ea60d917ede9ee3cf714d")

def start_peer(name):
    """
    Start a peer that already exists on the local file system
    :param name: the name of the peer
    :return:
    """
    peer = tiny.load_identity(name)

    appli = peer.resume_app("chat")
    appli.set_callback(lambda msg, from_, pkt, log: callback(peer, name, msg, from_, pkt, log))
    appli.resume_inst('0')  # '0' is the default key for the first app
    return peer, appli

def callback(peer, name, msg, from_, packet, log):
    """
    Define a callback for managing incoming data
    :param peer: personal instance of Identity
    :param name: my name (string)
    :param msg: the message received
    :param from_: the fid of the "public" feed of the person that sent the message
    :param packet: the PACKET object, giving access to fid, typ, sequence number, etc.
    :param log: the LOG object, giving access to the history of the log entries
    """
    try:
        msg = bipf.loads(msg)
    except KeyError: msg = str(msg)
    except TypeError: msg = str(msg)
    except UnicodeDecodeError: msg = str(msg)
    dbg(RED, f"{name} received \"{msg}\" from {peer.get_contact_alias(from_)} (#{packet.seq})")

def initialise():
    """
    Initialise 3 peers
    :return:
    """
    tiny.erase_all()
    peers = {}
    # For each peer, generate the default logs, create an app with one instance
    name_list = ["Alice", "Bob", "Charlie"]

    for n in ["Alice", "Bob"]:
        peers[n] = tiny.generate_id(n)
        peers[n].define_app("chat", APP_ID)

    peers['Charlie'] = tiny.generate_id('Charlie')
    appli = peers['Charlie'].define_app("chat", APP_ID)

    # Add mutual trust (follow) for the peers
    for n in name_list:
        for friend in name_list:
            if friend != n:
                peers[n].follow(peers[friend].public, friend)

    # Create the instance in only one peer who automatically invites the others to join
    appli.create_inst(['Alice', 'Bob'])
    return peers

def wait_for_instances(peers):
    for p in peers:
        a = peers[p].resume_app("chat")
        a.resume_inst('0')
        for m in a.instances['0']['m']:
            if a.instances['0'].get('n') == '':
                raise NotFoundTinyException("Instance not fully initiated yet")
            if a.instances['0']['m'][m].get('r') is None:
                raise NotFoundTinyException("Instance not fully initiated yet")
    return True

if __name__ == "__main__":
    if sys.argv[1] in ["Alice", "Bob", "Charlie"]:
        peer_name = sys.argv[1]
        identity, app = start_peer(peer_name)
        demo = DEMO(identity, app)
        demo.demo_loop(peer_name)

    elif sys.argv[1] == "init":
        peer_list = initialise()
        while True:
            # Wait for sync: all peers must create the instance first
            try:
                wait_for_instances(peer_list)
                exit(0)
            except NotFoundTinyException:
                time.sleep(0.5)

# eof
