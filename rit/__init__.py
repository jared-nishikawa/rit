from rit.index import IndexWrapper, TreeEntry, ExtensionEntry, Tree
from rit.pack import PackParser, IndexParser
from rit.objects import ObjectParser
from rit.color import yellow, green
from collections import OrderedDict

import urllib.request
import argparse
import binascii
import hashlib
import os
import sys
import time
import zlib


__version__ = "0.0.0"
__description__ = "rickety git"
__author__ = ""
__author_email__ = ""

git = '.git'
here = os.getcwd()

def find_git():
    success = True
    current = here
    while not os.path.isdir(os.path.join(current, git)):
        current = os.path.abspath(current + "/..")
        if current == '/':
            success = False
            break
    return success, current

gitexists, gitdir = find_git()
if gitexists:
    os.chdir(gitdir)

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


def cur_objects():
    ref = head()
    hsh = rev_parse(ref).strip()
    op = ObjectParser(hsh)
    c = op.parse()
    op = ObjectParser(c.tree)
    t = op.parse()
    return t.walk()


def cat_file(hsh, type_only=False):
    op = ObjectParser(hsh)
    obj = op.parse()
    if type_only:
        return obj.type
    return obj.encode()


def update_index(mode, hsh, filename):
    i = IndexWrapper()
    i.add_entry(mode, binascii.unhexlify(hsh), filename)
    e,gitdir = find_git()
    os.chdir(gitdir)
    i.write()


def update_ref(ref, hsh):
    path = os.path.join(git, ref)
    dirname = os.path.dirname(path)
    if not os.path.isdir(dirname):
        os.makedirs(dirname)
    with open(f".git/{ref}", 'w') as f:
        f.write(hsh + '\n')


def add(fname):
    relative = here[len(gitdir):].lstrip('/')
    fn = os.path.join(relative, fname)
    h = hash_object(fn, write=True)
    i = IndexWrapper()
    i.add_entry(0o100644, binascii.unhexlify(h), fn)
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
            return f.read().strip()
    return ''


def commit(msg):
    h = write_tree()
    ref = head()
    parent = rev_parse(ref)
    tree = write_tree()
    hsh = commit_tree(msg, tree, parent)
    update_ref(ref, hsh)


def checkout(b, new=None):
    if new:
        if not create_branch(new):
            return
        b = new
    change_branch(b)


def change_branch(b):
    ref = f"refs/heads/{b}"
    path = f".git/{ref}"
    if not os.path.isfile(path):
        print(f"Branch {b} does not exist")
        return
    with open(".git/HEAD", "w") as f:
        f.write(f"ref: {ref}")


def branch(b, delete=None):
    if delete:
        delete_branch(delete)
        return
    if not b:
        h = head()
        h = os.path.basename(h)
        for br in get_branches():
            if br == h:
                print(f"* {green(br)}")
            else:
                print(f"  {br}")
        return
    create_branch(b)


def create_branch(b):
    if is_branch(b):
        print(f"fatal: A branch named '{b}' already exists")
        return False
    ref = f"refs/heads/{b}"
    curref = head()
    if not curref:
        return False
    cur = rev_parse(curref)
    update_ref(ref, cur)
    return True


def is_branch(b):
    ref = f"refs/heads/{b}"
    path = os.path.join(gitdir, git, ref)
    if os.path.isfile(path):
        return True
    return False


def delete_branch(b):
    curref = head()
    ref = f"refs/heads/{b}"
    if ref == curref:
        print(f"error: Cannot delete checked out branch '{b}'")
        return
    path = os.path.join(gitdir, git, ref)
    try:
        os.remove(path)
    except:
        print(f"error: branch '{b}' not found")


def get_branches():
    path = os.path.join(gitdir, git, 'refs', 'heads')
    return sorted(os.listdir(path))


def init():
    global gitdir
    global here
    if gitexists:
        print("Already in git repo")
        return
    here = os.getcwd()
    gitdir = here
    os.mkdir(git)
    os.mkdir(f'{git}/objects')
    os.mkdir(f'{git}/refs')
    os.mkdir(f'{git}/refs/heads')
    with open(f'{git}/HEAD', 'w') as f:
        f.write("ref: refs/heads/master\n")


def clone(repo):
    if gitexists:
        print("Already in git repo")
        return
    name = os.path.splitext(os.path.basename(repo))[0]
    if os.path.isdir(name) or os.path.isfile(name):
        print("File or directory already exists")
        return
    os.mkdir(name)
    os.chdir(name)
    print(f"Cloning into '{name}'...")
    init()
    hsh = http_transfer_meta(repo)
    path = http_transfer(repo, hsh)
    index_pack(path, show=False)
    unpack_objects(path)
    ref = head()
    update_ref(ref, hsh)
    set_working_commit(hsh)
    name = "origin"
    add_remote(name, repo)
    update_ref(f"refs/remotes/{name}/master", hsh)


def http_transfer_meta(repo):
    url = f"{repo}/info/refs?service=git-upload-pack"
    req = urllib.request.urlopen(url)
    data = req.read()

    assert data[:30] == b"001e# service=git-upload-pack\n"
    data = data[30:]
    assert data[:4] == b"0000"
    data = data[4:]
    hsh = b""
    while 1:
        i = data[:4]
        n = int(i, 16)
        msg,data = data[:n], data[n:]
        if msg.endswith(b"refs/heads/master\n"):
            hsh = msg[4:44]
        if not n:
            break
    if not hsh:
        raise Exception

    hsh = hsh.decode()
    return hsh


def http_transfer(repo, hsh):
    url = f"{repo}/git-upload-pack"

    body = f"0098want {hsh} multi_ack_detailed no-done side-band-64k thin-pack ofs-delta deepen-since deepen-not agent=git/2.17.1\n00000009done\n"
    body = body.encode()

    req = urllib.request.Request(url, body)
    req.add_header("Content-Type", "application/x-git-upload-pack-request")

    r = urllib.request.urlopen(req)
    data = r.read()

    packdata = b''
    while 1:
        i,data = data[:4], data[4:]
        n = int(i, 16)-4
        msg,data = data[:n], data[n:]
    
        try:
            if msg[0] == 2:
                sys.stdout.write(msg[1:].decode())
            elif msg[0] == 1:
                packdata += msg[1:]

        except:
            break

    dirname = os.path.join(git, 'objects', 'pack')
    if not os.path.isdir(dirname):
        os.makedirs(dirname)
    
    h = binascii.hexlify(packdata[-20:]).decode()
    path = os.path.join(git, 'objects', 'pack', f'pack-{h}.pack')
    with open(path, 'wb') as f:
        f.write(packdata)
    return path


def index_pack(packfile, show=True):
    os.chdir(here)
    if not os.path.isfile(packfile):
        print(f"fatal: cannot open packfile '{packfile}': No such file or directory")
        return
    with open(packfile, 'rb') as f:
        data = f.read()
    p = PackParser(data)
    p.parse_without_index()
    index = p.create_index()
    sha = index[-40:-20]
    #print(sha)
    if show:
        print(binascii.hexlify(sha).decode())
    base = os.path.splitext(packfile)[0]
    path = '.'.join((base, 'idx'))
    with open(path, 'wb') as f:
        f.write(index)


def unpack_objects(packfile):
    base = os.path.splitext(packfile)[0]
    idxfile = '.'.join((base, 'idx'))
    with open(idxfile, 'rb') as f:
        ip = IndexParser(f.read())
    idx = ip.parse()

    with open(packfile, 'rb') as f:
        p = PackParser(f.read(), index=idx)
    p.parse_without_index()
    objdir = os.path.join(git, 'objects')
    p.write_objects(objdir)


def set_working_commit(commit):
    _,gitdir = find_git()
    os.chdir(gitdir)
    data = cat_file(commit)
    for line in data.split(b'\n'):
        if line.startswith(b'tree'):
            tree = line.strip().split()[1].decode()
            break
    else:
        print("No tree found in commit")
        return
    set_working_tree(tree)


def set_working_tree(tree, dname='.'):
    data = cat_file(tree)
    for line in data.split(b'\n'):
        line = line.strip()
        if not line:
            continue
        mode, typ, hsh, name = line.split()
        mode = int(mode, 8)
        hsh = hsh.decode()
        name = name.decode()
        fullname = os.path.join(dname, name)
        if typ == b"blob":
            set_working_blob(hsh, fullname)
            if fullname.startswith('./'):
                fullname = fullname[2:]
            update_index(mode, hsh, fullname)
        elif typ == b"tree":
            set_working_tree(hsh, fullname)


def set_working_blob(blob, name):
    data = cat_file(blob)
    dirname = os.path.dirname(name)
    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    with open(name, 'wb') as f:
        f.write(data)


def add_remote(name, url):
    os.chdir(gitdir)
    cfg = os.path.join(git, 'config')
    with open(cfg, 'w') as f:
        f.write(f'[remote "{name}"]\n')
        f.write(f'    url = {url}\n')
        f.write(f'fetch = +refs/heads/*:refs/remotes/{name}/*\n')
        f.write('[branch "master"]\n')
        f.write(f'    remote = {name}\n')
        f.write('    merge = refs/heads/master\n')


def all_refs():
    os.chdir(gitdir)
    refdir = os.path.join(git, 'refs')
    heads_path = os.path.join(git, 'refs', 'heads')
    remotes_path = os.path.join(git, 'refs', 'remotes')
    refs = {}
    for dname, dirs, files in os.walk(refdir):
        for fname in files:
            full = os.path.join(dname, fname)
            hsh = rev_parse(full[len(git):])
            if os.path.commonpath((full, heads_path)) == heads_path:
                key = full[len(heads_path):].lstrip('/')
            elif os.path.commonpath((full, remotes_path)) == remotes_path:
                key = full[len(remotes_path):].lstrip('/')
            refs[hsh] = refs.get(hsh, []) + [key]
    return refs


def log(oneline):
    refs = all_refs()
    h = head()
    ref = rev_parse(h)
    stack = [ref]
    while stack:
        ref = stack[0]
        del stack[0]

        op = ObjectParser(ref)
        commit = op.parse()
        if oneline:
            print(yellow(commit.hash[:8]), end=' ')
            print(commit.message.decode().split('\n')[0])
        else:
            print(yellow(commit.hash), end=' ')
            if commit.hash in refs:
                print("(", end='')
                print(', '.join(refs[commit.hash]), end='')
                print(')')
            print()
            print(commit.message.decode())
            print()
        stack = commit.parents + stack
        #ref = commit.parents[0]


def to_be_committed():
    # Contents of last commit
    last = dict(cur_objects())
    
    # In index
    i = IndexWrapper()
    results = []

    for name,hsh in i.entries():
        chk = last.get(name)
        if not chk:
            results.append(("new file", name.decode()))
        elif hsh != last.get(name):
            results.append(("modified", name.decode()))

    return results


def not_staged():
    # Need to parse gitignore and do regex :(
    os.chdir(gitdir)
    for dirname, dirs, files in os.walk('.'):
        for f in files:
            full = os.path.join(dirname, f)[2:]
            if full.startswith(".git/"):
                continue
            #print(full)



def untracked():
    pass


def status():
    b = os.path.basename(head())
    print(f"On branch {b}")
    changed = False

    comm = to_be_committed()
    if comm:
        changed = True
        print("Changes to be committed:")
        print('  (use "git reset HEAD <file>..." to unstage)')
        print()
        for s,c in comm:
            print(green(f"        {s}:   {c}"))
        print()

    ns = not_staged()
    if ns:
        changed = True
        print("Changes not staged for commit:")
        print('  (use "git add <file>..." to update what will be committed)')
        print('  (use "git checkout -- <file>..." to discard changes in working directory)')
        print()
        for s in ns:
            print(f"        modified:   {s}")
        print()

    uf = untracked()
    if uf:
        changed = True
        print("Untracked files:")
        print('  (use "git add <file>..." to include in what will be committed)')
        print()
        for f in uf:
            print(f"        {f}")
        print()

    if not changed:
        print("nothing to commit, working tree clean")

"""
On branch dev
Changes to be committed:
  (use "git reset HEAD <file>..." to unstage)

	modified:   rit/__init__.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git checkout -- <file>..." to discard changes in working directory)

	modified:   rit/__init__.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)

	file.txt
"""



    
def main():
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
    br.add_argument("branch", nargs='?', default="")
    br.add_argument("--delete", "-d")

    ch = subparsers.add_parser("checkout")
    ch.add_argument("branch", nargs='?', default="")
    ch.add_argument("-b", "--new-branch")

    it = subparsers.add_parser("init")

    st = subparsers.add_parser("status")

    cl = subparsers.add_parser("clone")
    cl.add_argument("repo")

    ip = subparsers.add_parser("index-pack")
    ip.add_argument("packfile")

    uo = subparsers.add_parser("unpack-objects")
    uo.add_argument("packfile")

    lg = subparsers.add_parser("log")
    lg.add_argument("--oneline", action="store_true")

    rm = subparsers.add_parser("remote")
    rm_subparsers = rm.add_subparsers(dest="remote_action")
    rm_add = rm_subparsers.add_parser("add")
    rm_add.add_argument("name")
    rm_add.add_argument("url")

    rm_rem = rm_subparsers.add_parser("remove")
    rm_rem.add_argument("name")

    args = parser.parse_args()
    action = args.action
    if action == "write-tree":
        h = write_tree()
        print(h)
    elif action == "hash-object":
        print(hash_object(args.filename, write=args.w))
    elif action == "cat-file":
        if args.p:
            print(cat_file(args.p).decode(), end='')
        elif args.t:
            print(cat_file(args.t, type_only=True).decode())
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
        branch(args.branch, delete=args.delete)

    elif action == "checkout":
        checkout(args.branch, new=args.new_branch)

    elif action == "init":
        init()

    elif action == "status":
        status()

    elif action == "clone":
        clone(args.repo)

    elif action == "index-pack":
        index_pack(args.packfile)

    elif action == "unpack-objects":
        unpack_objects(args.packfile)

    elif action == "remote":
        if args.remote_action == "add":
            add_remote(args.name, args.url)
        elif args.remote_action == "remove":
            pass

    elif action == "log":
        log(args.oneline)

    else:
        parser.print_help()
