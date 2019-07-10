from index import IndexWrapper, TreeEntry, ExtensionEntry, Tree
from collections import OrderedDict

import argparse
import binascii
import hashlib
import os
import sys
import time
import zlib


git = '.git'

def find_git():
    success = True
    while not os.path.isdir(git):
        os.chdir('..')
        if os.getcwd() == '/':
            success = False
            break
    return success, os.getcwd()
        

def write_tree():
    iw = IndexWrapper()
    i = iw.index
    root = Tree()
    for e in i.entries:
        root.add(e)
    trees = []
    for name, t in root.iter():
        ec = t.entry_count
        sc = len(t['dirs'])
        h,z = t.hash()
        write_object(h, z)
        te = TreeEntry(name, ec, sc, h)
        trees.append(te)
    ee = ExtensionEntry(b'TREE', trees)
    i.set_ext(ee)
    iw.write()

    h,_ = root.hash()
    return binascii.hexlify(h).decode()

def hash_blob(fname):
    with open(fname, 'rb') as f:
        data = f.read()
    length = len(data)
    blob = f"blob {length}".encode()
    blob += b"\x00"
    blob += data
    zipped = zlib.compress(blob)
    h = hashlib.sha1(blob).digest()
    return h, zipped


def hash_object(fname, write=False):
    h,z = hash_blob(fname)

    if write:
        write_object(h, z)
    return binascii.hexlify(h).decode()


def commit_tree(msg, tree, parent=''):
    data = b""
    data += f"tree {tree}\n".encode()
    if parent:
        parent = parent.strip()
        data += f"parent {parent}\n".encode()
    now = int(time.time())
    tz = time.strftime("%z")
    data += f"author Jared Nishikawa <jnishikawa@carbonblack.com> "\
            f"{now} {tz}\n".encode()
    data += f"committer Jared Nishikawa <jnishikawa@carbonblack.com> "\
            f"{now} {tz}\n".encode()
    data += b"\n"
    data += msg.encode()
    length = len(data)
    commit = f"commit {length}".encode()
    commit += b"\x00"
    commit += data
    zipped = zlib.compress(commit)
    h = hashlib.sha1(commit).digest()
    write_object(h, zipped)
    return binascii.hexlify(h).decode()


def write_object(_h, zipped):
    h = binascii.hexlify(_h).decode()
    path = f".git/objects/{h[:2]}/{h[2:]}"
    dirname = os.path.dirname(path)

    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    if os.path.isfile(path):
        os.chmod(path, 0o644)
    with open(path, "wb") as f:
        f.write(zipped)
    os.chmod(path, 0o444)

def cat_file(hsh, type_only=False):
    fname = f".git/objects/{hsh[:2]}/{hsh[2:]}"
    with open(fname, "rb") as f:
        data = f.read()
    text = zlib.decompress(data)
    spl = text.split(b' ', maxsplit=1)
    assert len(spl) == 2
    h,text = spl
    if type_only:
        return h.decode()
    n,rest = text.split(b'\x00', 1)
    n = int(n)
    assert len(rest) == n
    if h == b'blob':
        return rest.decode()
    elif h == b'tree':
        result = []
        entries = []
        while rest:
            perms,rest = rest.split(b' ', maxsplit=1)
            name,rest = rest.split(b'\x00', maxsplit=1)
            hsh,rest = rest[:20], rest[20:]
            entry = (perms, name, hsh)
            entries.append(entry)
        for perms, name, hsh in entries:
            if perms.startswith(b'1'):
                typ = 'blob'
            else:
                typ = 'tree'
            p = int(perms, 8)
            h = binascii.hexlify(hsh).decode()
            n = name.decode()
            result.append(f"{p:06o} {typ} {h}    {n}\n")
        return ''.join(result)
    elif h == b'commit':
        return rest.decode()

def update_index(mode, hsh, filename):
    i = IndexWrapper()
    i.add_entry(mode, binascii.unhexlify(hsh), filename)

def update_ref(ref, hsh):
    with open(f".git/{ref}", 'w') as f:
        f.write(hsh + '\n')

def add(fname):
    h = hash_object(fname, write=True)
    i = IndexWrapper()
    i.add_entry(0o100644, binascii.unhexlify(h), fname)
    i.write()

def head():
    with open(".git/HEAD") as f:
        data = f.read()
        ref = data.split(':')[1].strip()
    return ref

def rev_parse(ref):
    path = f".git/{ref}"
    if os.path.isfile(path):
        with open(f".git/{ref}") as f:
            return f.read()
    return ''

def commit(msg):
    h = write_tree()
    ref = head()
    parent = rev_parse(ref)
    tree = write_tree()
    hsh = commit_tree(msg, tree, parent)
    update_ref(ref, hsh)


def checkout(b):
    ref = f"refs/heads/{b}"
    path = f".git/{ref}"
    if not os.path.isfile(path):
        print(f"Branch {b} does not exist")
        return
    with open(".git/HEAD", "w") as f:
        f.write(f"ref: {ref}")


def branch(b):
    ref = f"refs/heads/{b}"
    curref = head()
    if not cur:
        return
    cur = rev_parse(curref)
    update_ref(ref, cur)


def init():
    here = os.getcwd()
    exists, gitdir = find_git()
    if exists:
        print("Already in git repo")
        return
    os.chdir(here)
    os.mkdir(git)
    os.mkdir(f'{git}/objects')
    os.mkdir(f'{git}/refs')
    os.mkdir(f'{git}/refs/heads')
    with open(f'{git}/HEAD', 'w') as f:
        f.write("ref: refs/heads/master\n")

    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action")

    wt = subparsers.add_parser("write-tree")

    ho = subparsers.add_parser("hash-object")
    ho.add_argument("-w", action="store_true")
    ho.add_argument("filename")

    cf = subparsers.add_parser("cat-file")
    cf.add_argument("-p")
    cf.add_argument("-t")

    ui = subparsers.add_parser("update-index")
    ui.add_argument("mode")
    ui.add_argument("hash")
    ui.add_argument("filename")

    ad = subparsers.add_parser("add")
    ad.add_argument("filename")

    cm = subparsers.add_parser("commit")
    cm.add_argument("--message", "-m", required=True)

    ct = subparsers.add_parser("commit-tree")
    ct.add_argument("-m", "--message")
    ct.add_argument("-p", "--parent", required=True)
    ct.add_argument("tree")

    ur = subparsers.add_parser("update-ref")
    ur.add_argument("ref")
    ur.add_argument("hash")

    br = subparsers.add_parser("branch")
    br.add_argument("branch")
    br.add_argument("-d")

    ch = subparsers.add_parser("checkout")
    ch.add_argument("branch")

    it = subparsers.add_parser("init")

    args = parser.parse_args()
    action = args.action
    if action == "write-tree":
        h = write_tree()
        print(h)
    elif action == "hash-object":
        print(hash_object(args.filename, write=args.w))
    elif action == "cat-file":
        if args.p:
            print(cat_file(args.p), end='')
        elif args.t:
            print(cat_file(args.t, type_only=True))
    elif action == "update-index":
        update_index(args.mode, args.hash, args.filename)
        
    elif action == "add":
        add(args.filename)

    elif action == "commit":
        commit(args.message)

    elif action == "commit-tree":
        if not args.message:
            msg = sys.stdin.read()
        else:
            msg = args.message
        print(commit_tree(msg, args.tree, args.parent))

    elif action == "update-ref":
        update_ref(args.ref, args.hash)

    elif action == "branch":
        branch(args.branch)

    elif action == "checkout":
        checkout(args.branch)

    elif action == "init":
        init()




