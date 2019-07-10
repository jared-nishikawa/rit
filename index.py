from collections import OrderedDict

import struct
import binascii
import os
import hashlib
import zlib


def unpack_num(p):
    if len(p) == 4:
        return struct.unpack(">I", p)[0]
    elif len(p) == 2:
        return struct.unpack(">H", p)[0]


def pack_num(n, l):
    if l == 4:
        return struct.pack(">I", n)
    elif l == 2:
        return struct.pack(">H", n)


class Parser:
    def __init__(self, data):
        self.data = data
        self.mylen = 0

    def parse(self, length):
        ret,self.data = self.data[:length], self.data[length:]
        self.mylen += length
        return ret

    def rest(self):
        return self.data

    def parse_to(self, char):
        spl = self.data.split(char, maxsplit=1)
        if len(spl) != 2:
            raise ValueError(f"Char not found: {char}")
        ret,self.data = spl
        self.mylen += len(ret) + 1
        return ret


class IndexEntry:
    def __init__(self,
            c_sec, c_nano, m_sec, m_nano,
            dev, ino, mode,
            uid, gid, size, sha1, flags, v3_extend, entry_path_name):
        self.c_sec = c_sec
        self.c_nano = c_nano
        self.m_sec = m_sec
        self.m_nano = m_nano
        self.dev = dev
        self.ino = ino
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.size = size
        self.sha1 = sha1
        self.flags = flags
        self.v3_extend = v3_extend
        self.entry_path_name = entry_path_name
        self.assume_valid = (flags >> 15) & 1
        self.stage = (flags >> 12) & 0b11

        self.obj = (mode >> 12) & 0xf
        self.perms = mode & 0o777

    def encode(self):
        b = b""
        b += pack_num(self.c_sec, 4)
        b += pack_num(self.c_nano, 4)
        b += pack_num(self.m_sec, 4)
        b += pack_num(self.m_nano, 4)
        b += pack_num(self.dev, 4)
        b += pack_num(self.ino, 4)
        b += pack_num(self.mode, 4)
        b += pack_num(self.uid, 4)
        b += pack_num(self.gid, 4)
        b += pack_num(self.size, 4)
        b += self.sha1
        b += pack_num(self.flags, 2)
        extended = (self.flags >> 14) & 1
        if extended:
            b += pack_num(self.v3_extend, 2)
        b += self.entry_path_name
        pad_len = 8 - (len(b) % 8)
        b += b"\x00"*pad_len
        return b


class IndexEntryParser(Parser):
    def read(self):
        c_sec = unpack_num(self.parse(4))
        c_nano = unpack_num(self.parse(4))
        m_sec = unpack_num(self.parse(4))
        m_nano = unpack_num(self.parse(4))
        dev = unpack_num(self.parse(4))
        ino = unpack_num(self.parse(4))
        mode = unpack_num(self.parse(4))

        #obj = (mode >> 12) & 0xf
        #perm = mode & 0o777

        uid = unpack_num(self.parse(4))
        gid = unpack_num(self.parse(4))
        size = unpack_num(self.parse(4))
        sha1 = self.parse(20)
        flags = unpack_num(self.parse(2))

        assume_valid = (flags >> 15) & 1
        extended = (flags >> 14) & 1
        stage = (flags >> 12) & 0b11
        name_len = flags & 0xfff

        if extended:   
            v3_extend = unpack_num(self.parse(2))
        else:
            v3_extend = 0

        entry_path_name = self.parse(name_len)
        pad_len = 8 - (self.mylen % 8)
        pad = self.parse(pad_len)
        return IndexEntry(
                c_sec, c_nano, m_sec, m_nano,
                dev, ino, mode,
                uid, gid, size, sha1, flags, v3_extend, entry_path_name)


class ExtensionEntry:
    def __init__(self,
            sig, data):
        self.sig = sig
        self.data = data

    @property
    def size(self):
        return len(self.encoded_data())

    def encoded_data(self):
        encoded = b''
        if self.sig == b'TREE':
            for tree in self.data:
                encoded += tree.encode()
        return encoded

    def encode(self):
        b = b''
        b += self.sig
        b += pack_num(self.size, 4)
        b += self.encoded_data()
        return b


class ExtensionEntryParser(Parser):
    def read(self):
        sig = self.parse(4)
        size = unpack_num(self.parse(4))
        extdata,self.data = self.data[:size], self.data[size:]
        if sig == b'TREE':
            trees = []
            while extdata:
                tp = TreeEntryParser(extdata)
                t = tp.read()
                trees.append(t)
                extdata = tp.rest()
            return ExtensionEntry(sig, trees)


class TreeEntry:
    def __init__(self,
            path, entry_count, subtree_count, hsh):
        self.path = path
        self.entry_count = entry_count
        self.subtree_count = subtree_count
        self.hash = hsh

    def encode(self):
        b = b''
        b += self.path + b"\x00"
        b += str(self.entry_count).encode() + b" "
        b += str(self.subtree_count).encode() + b"\n"
        b += self.hash
        return b


class TreeEntryParser(Parser):
    def read(self):
        path = self.parse_to(b"\x00")
        entry_count = int(self.parse_to(b" "))
        subtree_count = int(self.parse_to(b"\n"))
        if entry_count == -1:
            return TreeEntry(path, entry_count, subtree_count, b'')
        hsh = self.parse(20)
        return TreeEntry(path, entry_count, subtree_count, hsh)


class Index:
    def __init__(self,
            sig, ver, entries, exts):
        self.sig = sig
        self.ver = ver
        #self._num = num
        self.entries = entries
        self.exts = exts

    @property
    def num(self):
        return len(self.entries)

    def set_ext(self, ext):
        for idx,e in enumerate(self.exts):
            if e.sig == ext.sig:
                self.exts[idx] = ext
                break
        else:
            self.exts.append(ext)

    def add_entry(self, mode, hsh, filename):
        stat = os.stat(filename)
        c_sec = int(stat.st_ctime)
        c_nano = int(1000000000*(stat.st_ctime%1))
        m_sec = int(stat.st_mtime)
        m_nano = int(1000000000*(stat.st_mtime%1))
        dev = stat.st_dev
        ino = stat.st_ino
        mode = mode
        uid = stat.st_uid
        gid = stat.st_gid
        size = stat.st_size
        sha1 = hsh
        flags = len(filename) & 0xfff
        v3_extend = 0
        entry_path_name = filename.encode()
        entry = IndexEntry(
                c_sec, c_nano, m_sec, m_nano,
                dev, ino, mode,
                uid, gid, size, sha1, flags, v3_extend, entry_path_name)
        changed = False
        for i,existing_entry in enumerate(self.entries):
            if existing_entry.entry_path_name == entry_path_name:
                if existing_entry.sha1 == sha1:
                    break
                self.entries[i] = entry
                changed = True
                break
        else: 
            self.entries.append(entry)
            changed = True
        if changed:
            self

        containing = set(trees_containing(entry_path_name))
        for ext in self.exts:
            if ext.sig == b'TREE':
                for tree in ext.data:
                    if tree.hash in containing:
                        tree.entry_count = -1
                        tree.hash = b''


    def encode(self):
        b = b''
        b += self.sig
        b += pack_num(self.ver, 4)
        b += pack_num(self.num, 4)
        sorted_entries = sorted(self.entries, key=lambda x: x.entry_path_name)
        for e in sorted_entries:
            b += e.encode()
        for e in self.exts:
            b += e.encode()
        h = hashlib.sha1(b).digest()
        b += h
        return b


class IndexParser(Parser):
    def read(self):
        header = self.parse(12)
        sig = header[:4]
        ver = unpack_num(header[4:8])
        num = unpack_num(header[8:])
        entries = []
        exts = []
        for _ in range(num):
            ip = IndexEntryParser(self.data)
            i = ip.read()
            entries.append(i)
            self.data = ip.rest()

        while len(self.data) > 20:
            ep = ExtensionEntryParser(self.data)
            e = ep.read()
            exts.append(e)
            self.data = ep.rest()
        hsh = self.data
        return Index(sig, ver, entries, exts)


class IndexWrapper:
    def __init__(self):
        self.fname = './.git/index'
        if not os.path.isfile(self.fname):
            self.index = Index(b'DIRC', 2, [], [])
        else:
            with open(self.fname, 'rb') as f:
                data = f.read()
            ip = IndexParser(data)
            self.index = ip.read()

    def show(self):
        print(self.index.sig, self.index.ver, self.index.num)
        for e in self.index.entries:
            print(e.entry_path_name, binascii.hexlify(e.sha1))
        for e in self.index.exts:
            print(e.sig)
            if e.sig == b'TREE':
                for t in e.data:
                    print(
                            t.path,
                            t.entry_count,
                            t.subtree_count,
                            binascii.hexlify(t.hash))

    def write(self):
        with open(self.fname, 'wb') as f:
            f.write(self.index.encode())

    def add_entry(self, mode, hsh, filename):
        return self.index.add_entry(mode, hsh, filename)

    def encode(self):
        return self.index.encode()


def trees_containing(path):
    hashes = []
    i = IndexWrapper().index
    root = Tree(key=lambda x: os.path.commonpath([path, x.root]) == x.root)
    for e in i.entries:
        root.add(e)
    for name, t in root.iter():
        if t.marked():
            h,_ = t.hash()
            hashes.append(h)
    return hashes


class Tree(dict):
    def __init__(self, root=b'', key=lambda x: None):
        self['files'] = []
        self['dirs'] = OrderedDict()
        self.root = root
        self.entry_count = 0
        self.key = key

    def marked(self):
        return self.key(self)

    def add(self, indexentry):
        path = indexentry.entry_path_name
        dirname,fname = os.path.split(path)
        if os.path.commonpath([dirname, self.root]) == self.root:
            dirname = dirname[len(self.root):].lstrip(b'/')
        if len(dirname) == 0:
            parts = []
        else:
            parts = dirname.split(b'/')
        cur = self
        for part in parts:
            cur.entry_count += 1
            if part not in cur['dirs']:
                new = Tree(key=self.key)
                new.root = os.path.join(cur.root, part)
                cur['dirs'][part] = new
            cur = cur['dirs'][part]
        cur['files'].append((fname, indexentry))
        cur.entry_count += 1

    def iter(self):
        stack = [(b'', self)]
        while stack:
            name, cur = stack[0]
            del stack[0]
            stack = [(t, cur['dirs'][t]) for t in cur['dirs']] + stack
            yield name, cur

    def hash(self):
        items = []
        for fname,entry in self['files']:
            items.append((fname, entry, 0))
        for dname in self['dirs']:
            items.append((dname, self['dirs'][dname], 1))
        sorted_items = sorted(items)
        data = b''
        for name, obj, flag in sorted_items:
            # 0 is file, 1 is tree
            if flag == 0:
                e = obj
                mode = e.obj << 12 | e.perms
                mode_s = f'{mode:06o}'.encode()
                entry_data = b''
                entry_data += mode_s + b' '
                entry_data += name + b'\x00'
                entry_data += e.sha1
                data += entry_data
            elif flag == 1:
                t = obj
                mode = b'40000'
                entry_data = b''
                entry_data += mode + b' '
                entry_data += name + b'\x00'
                hsh,_ = t.hash()
                entry_data += hsh
                data += entry_data

        length = len(data)
        tree = f"tree {length}".encode()
        tree += b"\x00"
        tree += data
        zipped = zlib.compress(tree)
        h = hashlib.sha1(tree).digest()
        return h, zipped


if __name__ == '__main__':
    i = IndexWrapper()
    i.show()
