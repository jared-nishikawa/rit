import zlib
import binascii
import os


class GitObject:
    def __init__(self, typ, data, hsh):
        self.type = typ
        self.data = data
        self.hash = hsh


class GitTree(GitObject):
    def __init__(self, typ, data, hsh, dirname=b''):
        super().__init__(typ, data, hsh)
        entries = []
        while data:
            perms,data = data.split(b' ', maxsplit=1)
            name,data = data.split(b'\x00', maxsplit=1)
            hsh,data = data[:20], data[20:]
            entry = (perms, name, binascii.hexlify(hsh).decode())
            entries.append(entry)
        self.entries = entries
        self.dirname = dirname

    def encode(self):
        result = []
        for perms, name, hsh in self.entries:
            if perms.startswith(b'1'):
                typ = 'blob'
            else:
                typ = 'tree'
            p = int(perms, 8)
            n = name.decode()
            result.append(f"{p:06o} {typ} {hsh}    {n}\n")
        return ''.join(result).encode()

    def walk(self):
        result = []
        for perms, name, hsh in self.entries:
            if perms.startswith(b'1'):
                typ = 'blob'
            else:
                typ = 'tree'
            full = os.path.join(self.dirname, name)
            if typ == 'tree':
                op = ObjectParser(hsh, dirname=full)
                t = op.parse()
                result += t.walk()
            else:
                result.append((full, hsh))
        return result


class GitBlob(GitObject):
    def encode(self):
        return self.data


class GitCommit(GitObject):
    def __init__(self, typ, data, hsh):
        super().__init__(typ, data, hsh)

        line,data = data.split(b'\n', maxsplit=1)
        assert line.startswith(b'tree')
        tree = line.split(maxsplit=1)[1]

        parents = []
        while 1:
            line,data = data.split(b'\n', maxsplit=1)
            parent = b''
            if line.startswith(b'parent'):
                parent = line.split(maxsplit=1)[1]
                parents.append(parent.decode())
            else:
                break
            #elif line.startswith(b'author'):
            #    author = line.split(maxsplit=1)[1]
            #    break
            #else:
            #    assert False
            #if parent:
            #    line,data = data.split(b'\n', maxsplit=1)
            #    assert line.startswith(b'author')
        assert line.startswith(b'author')
        author = line.split(maxsplit=1)[1]
        line,data = data.split(b'\n', maxsplit=1)
        assert line.startswith(b'committer')
        committer = line.split(maxsplit=1)[1]
        #assert data.startswith(b'\n')
        message = data.strip()
        #data = data[1:]
        #line = data.strip()
        #line,data = data.split(b'\n', maxsplit=1)
        #print(line)
        #message = line.split(maxsplit=1)[1]

        self.tree = tree
        self.parents = parents
        self.author = author
        self.committer = committer
        self.message = message

    def encode(self):
        return self.data


class ObjectParser:
    def __init__(self, hsh, dirname=b''):
        self.dirname = dirname
        self.hsh = hsh
        try:
            hsh = hsh.decode()
        except:
            pass
        fname = f".git/objects/{hsh[:2]}/{hsh[2:]}"
        with open(fname, "rb") as f:
            self.data = f.read()

    def parse(self):
        data = self.data
        text = zlib.decompress(data)
        spl = text.split(b' ', maxsplit=1)
        assert len(spl) == 2
        h,text = spl
        n,rest = text.split(b'\x00', 1)
        n = int(n)
        assert len(rest) == n

        if h == b'blob':
            return GitBlob(h, rest, self.hsh)

        elif h == b'tree':
            return GitTree(h, rest, self.hsh, dirname=self.dirname)

        elif h == b'commit':
            return GitCommit(h, rest, self.hsh)

