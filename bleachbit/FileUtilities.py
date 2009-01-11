# vim: ts=4:sw=4:expandtab
# -*- coding: UTF-8 -*-

## BleachBit
## Copyright (C) 2009 Andrew Ziem
## http://bleachbit.sourceforge.net
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
## 
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
## 
## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
File-related utilities
"""


import ConfigParser
import datetime
import glob
import locale
import os
import os.path
import shlex
import stat
import subprocess


HAVE_GNOME_VFS = True
try:
    import gnomevfs
except:
    try:
        # this is the deprecated name
        import gnome.vfs
    except:
        HAVE_GNOME_VFS = False
    else:
        gnomevfs = gnome.vfs

if not "iglob" in dir(glob):
    glob.iglob = glob.glob

from Options import options


class OpenFiles:
    """Cached way to determine whether a file is open by active process"""
    def __init__(self):
        self.last_scan_time = None
        self.files = []

    def file_qualifies(self, filename):
        """Return boolean wehether filename qualifies to enter cache (check \
        against blacklist)"""
        return not filename.startswith("/dev") and \
            not filename.startswith("/proc")

    def scan(self):
        """Update cache"""
        self.last_scan_time = datetime.datetime.now()
        self.files = []
        for filename in glob.iglob("/proc/*/fd/*"):
            try:
                target = os.path.realpath(filename)
            except TypeError:
                # happens, for example, when link points to
                # '/etc/password\x00 (deleted)'
                continue
            if self.file_qualifies(target):
                self.files.append(target)

    def is_open(self, filename):
        """Return boolean whether filename is open by running process"""
        if None == self.last_scan_time or (datetime.datetime.now() - 
            self.last_scan_time).seconds > 10:
            self.scan()
        return filename in self.files


def bytes_to_human(bytes):
    """Display a file size in human terms (megabytes, etc.)"""

    storage_multipliers = { 1024**5 : 'PB', 1024**4 : 'TB', \
        1024**3 : 'GB', 1024**2: 'MB', 1024: 'KB', 1 : 'B' }

    if 0 == bytes:
        return "0"

    if bytes >= 1024**3:
        decimals = 2
    elif bytes >= 1024:
        decimals = 1
    else:
        decimals = 0

    for key in sorted(storage_multipliers.keys(), reverse = True):
        if bytes >= key:
            abbrev = (1.0 * bytes) / key
            suf = storage_multipliers[key]
            format = "%." + str(decimals) + "f" + suf
            if hasattr(locale, 'format_string'):
                return locale.format_string(format, abbrev)
            else:
                return locale.format(format, abbrev)

def children_in_directory(top, list_directories = False):
    """Iterate files and, optionally, subdirectories in directory"""
    for (dirpath, dirnames, filenames) in os.walk(top, topdown=False):
        if list_directories:
            for dirname in dirnames:
                yield os.path.join(dirpath, dirname)
        for filename in filenames:
            yield os.path.join(dirpath, filename)


def delete(path, shred = False):
    """Delete path that is either file, directory, link or FIFO"""
    print "info: removing '%s'" % (path,)
    mode = os.lstat(path)[stat.ST_MODE]
    if stat.S_ISFIFO(mode) or stat.S_ISLNK(mode):
        os.remove(path)
    elif stat.S_ISDIR(mode):
        os.rmdir(path)
    elif stat.S_ISREG(mode):
        if options.get('shred') or shred:
            # http://en.wikipedia.org/wiki/Data_remanence
            # 2006 NIST Special Publication 800-88 (p. 7): "Studies have
            # shown that most of today's media can be effectively cleared
            # by one overwrite"
            args = ["shred", "--remove", "--iterations=0", "--zero", path]
            ret = subprocess.check_call(args)
            if 0 != ret:
                raise Exception("shred subprocess returned non-zero error code " % (ret,))
        else:
            os.remove(path)
    else:
        raise Exception("Unsupported special file type")


def ego_owner(filename):
    """Return whether current user owns the file"""
    return os.lstat(filename).st_uid == os.getuid()


def exists_in_path(filename):
    """Returns boolean whether the filename exists in the path"""
    for dirname in os.getenv('PATH').split(":"):
        if os.path.exists(os.path.join(dirname, filename)):
            return True
    return False


def exe_exists(pathname):
    """Returns boolean whether executable exists"""
    if os.path.isabs(pathname):
        if not os.path.exists(pathname):
            return False
    else:
        if not exists_in_path(pathname):
            return False
    return True


def getsize(path):
    """Return the actual file size considering spare files
       and symlinks"""
    __stat = os.lstat(path)
    return __stat.st_blocks * 512


def __is_broken_xdg_desktop_application(config, desktop_pathname):
    """Returns boolean whether application deskop entry file is broken"""
    if not config.has_option('Desktop Entry', 'Exec'):
        print "info: is_broken_xdg_menu: missing required option 'Exec': '%s'" \
            % (desktop_pathname)
        return True
    exe = config.get('Desktop Entry', 'Exec').split(" ")[0]
    if not exe_exists(exe):
        print "info: is_broken_xdg_menu: executable '%s' does not exist '%s'" \
            % (exe, desktop_pathname)
        return True
    if 'env' == exe:
        # Wine v1.0 creates .desktop files like this
        # Exec=env WINEPREFIX="/home/z/.wine" wine "C:\\Program Files\\foo\\foo.exe"
        execs = shlex.split(config.get('Desktop Entry', 'Exec'))
        wineprefix = None
        del(execs[0])
        while True:
            if 0 <= execs[0].find("="):
                (name, value) = execs[0].split("=")
                if 'WINEPREFIX' == name:
                    wineprefix = value
                del(execs[0])
            else:
                break
        if not exe_exists(execs[0]):
            print "info: is_broken_xdg_menu: executable '%s'" \
                "does not exist '%s'" % (execs[0], desktop_pathname)
            return True
        # check the Windows executable exists
        if wineprefix:
            windows_exe = wine_to_linux_path(wineprefix, execs[1])
            if not os.path.exists(windows_exe):
                print "info: is_broken_xdg_menu: Windows executable" \
                    "'%s' does not exist '%s'" % \
                    (windows_exe, desktop_pathname)
                return True
    return False


def is_broken_xdg_desktop(pathname):
    """Returns boolean whether the given XDG desktop entry file is broken.
    Reference: http://standards.freedesktop.org/desktop-entry-spec/latest/"""
    config = ConfigParser.RawConfigParser()
    config.read(pathname)
    if not config.has_section('Desktop Entry'):
        print "info: is_broken_xdg_menu: missing required section " \
            "'Desktop Entry': '%s'" % (pathname)
        return True
    if not config.has_option('Desktop Entry', 'Type'):
        print "info: is_broken_xdg_menu: missing required option 'Type': '%s'" % (pathname)
        return True
    file_type = config.get('Desktop Entry', 'Type').strip().lower()
    if 'link' == file_type:
        if not config.has_option('Desktop Entry', 'URL') and \
            not config.has_option('Desktop Entry', 'URL[$e]'):
            print "info: is_broken_xdg_menu: missing required option 'URL': '%s'" % (pathname)
            return True
        return False
    if 'mimetype' == file_type:
        if not config.has_option('Desktop Entry', 'MimeType'):
            print "info: is_broken_xdg_menu: missing required option 'MimeType': '%s'" % (pathname)
            return True
        mimetype = config.get('Desktop Entry', 'MimeType').strip().lower()
        if HAVE_GNOME_VFS and 0 == len(gnomevfs.mime_get_all_applications(mimetype)):
            print "info: is_broken_xdg_menu: MimeType '%s' not " \
                "registered '%s'" % (mimetype, pathname)
            return True
        return False
    if 'application' != file_type:
        print "Warning: unhandled type '%s': file '%s'" % (file_type, pathname)
        return False
    if __is_broken_xdg_desktop_application(config, pathname):
        return True
    return False


def wine_to_linux_path(wineprefix, windows_pathname):
    """Return a Linux pathname from an absolute Windows pathname and Wine prefix"""
    drive_letter = windows_pathname[0]
    windows_pathname = windows_pathname.replace(drive_letter + ":", \
        "drive_" + drive_letter.lower())
    windows_pathname = windows_pathname.replace("\\","/")
    return os.path.join(wineprefix, windows_pathname)


openfiles = OpenFiles()


import unittest

class TestFileUtilities(unittest.TestCase):
    """Unit test for module FileUtilities"""

    def __touch(self, filename):
        """Create an empty file"""
        f = open(filename, "w")


    def __human_to_bytes(self, string):
        """Convert a string like 10.2GB into bytes"""
        multiplier = { 'B' : 1, 'KB': 1024, 'MB': 1024**2, \
            'GB': 1024**3, 'TB': 1024**4 }
        import re
        matches = re.findall("^([0-9]*)(\.[0-9]{1,2})?([KMGT]{0,1}B)$", string)
        if 2 > len(matches[0]):
            raise ValueError("Invalid input for '%s'" % (string))
        return int(float(matches[0][0]+matches[0][1]) * multiplier[matches[0][2]])


    def test_bytes_to_human(self):
        """Unit test for class bytes_to_human"""

        old_locale = locale.getlocale(locale.LC_NUMERIC)
        locale.setlocale(locale.LC_NUMERIC, 'en_US.utf8')

        # test one-way conversion for predefined values
        tests = [ ("0", bytes_to_human(0)),
                  ("1B", bytes_to_human(1)),
                  ("1.0KB", bytes_to_human(1024)),
                  ("1.0MB", bytes_to_human(1024**2)),
                  ("1.00GB", bytes_to_human(1024**3)),
                  ("1.00TB", bytes_to_human(1024**4)) ]

        for test in tests:
            self.assertEqual(test[0], test[1])

        # test roundtrip conversion for random values
        import random
        for n in range(0, 1000):
            bytes = random.randrange(0, 1024**4)
            human = bytes_to_human(bytes)
            bytes2 = self.__human_to_bytes(human)
            error =  abs(float(bytes2 - bytes) / bytes)
            self.assert_(abs(error) < 0.01, \
                "%d (%s) is %.2f%% different than %d" % \
                (bytes, human, error * 100, bytes2))

        # test localization
        if hasattr(locale, 'format_string'):
            try:
                locale.setlocale(locale.LC_NUMERIC, 'de_DE.utf8')
            except:
                print "Warning: exception when setlocale to de_DE.utf8"
            else:
                self.assertEqual("1,00TB", bytes_to_human(1024**4))

        # clean up
        locale.setlocale(locale.LC_NUMERIC, old_locale)


    def test_children_in_directory(self): 
        """Unit test for function children_in_directory()"""
        import tempfile

        # test an existing directory that usually exists
        dirname = os.path.expanduser("~/.config")
        for filename in children_in_directory(dirname, True):
            self.assert_ (type(filename) is str)
            self.assert_ (os.path.isabs(filename))
        for filename in children_in_directory(dirname, False):
            self.assert_ (type(filename) is str)
            self.assert_ (os.path.isabs(filename))
            self.assert_ (not os.path.isdir(filename))

        # test a constructed file in a constructed directory
        dirname = tempfile.mkdtemp()
        filename = os.path.join(dirname, "somefile")
        self.__touch(filename)
        for loopfilename in children_in_directory(dirname, True):
            self.assertEqual (loopfilename, filename)
        for loopfilename in children_in_directory(dirname, False):
            self.assertEqual (loopfilename, filename)
        os.remove(filename)

        # test subdirectory
        subdirname = os.path.join(dirname, "subdir")
        os.mkdir(subdirname)
        for filename in children_in_directory(dirname, True):
            self.assertEqual (filename, subdirname)
        for filename in children_in_directory(dirname, False):
            self.assert_ (False)
        os.rmdir(subdirname)

        os.rmdir(dirname)


    def test_delete(self):
        """Unit test for method delete()"""

        import tempfile

        hebrew = "עִבְרִית"
        katanana = "アメリカ"
        umlauts = "ÄäǞǟËëḦḧÏïḮḯÖöȪȫṎṏT̈ẗÜüǕǖǗǘǙǚǛǜṲṳṺṻẄẅẌẍŸÿ"

        tests = [ ('.suffix', 'prefix'), # simple
                  ("\t", "\t"), # tab
                  ("~`!@#$%^&*()-_+=", "x"), # non-alphanumeric characters
                  ("[]{};':,.?<>\|", "x"), # non-alphanumeric characters
                  ("x".zfill(100), ".y".zfill(100)), # long
                  (" ", " "), # space
                  ('"', "'"), # quotation marks
                  (u'a', u'a'), # simple unicode
                  (hebrew, hebrew),
                  (katanana, katanana),
                  (umlauts, umlauts) ]
        for test in tests:
            for shred in [True, False]:
                (fd, filename) = tempfile.mkstemp(test[0], 'bleachbit-test' + test[1])
                self.assert_(os.path.exists(filename))
                for x in range(0, 4096/5):
                    bytes = os.write(fd, "top secret")
                    self.assertEqual(bytes, 10)
                os.close(fd)
                self.assert_(os.path.exists(filename))
                delete(filename, shred)
                self.assert_(not os.path.exists(filename))

        # test symlink
        (fd, filename) = tempfile.mkstemp()
        os.close(fd)
        self.assert_(os.path.exists(filename))
        linkname = '/tmp/bleachbitsymlinktest'
        if os.path.lexists(linkname):
            delete(linkname)
        self.assert_(not os.path.lexists(linkname))
        os.symlink(filename, linkname)
        self.assert_(os.path.lexists(linkname))
        delete(linkname)
        self.assert_(os.path.exists(filename))
        self.assert_(not os.path.lexists(linkname))
        delete(filename)
        self.assert_(not os.path.exists(filename))

        # test broken symlink
        os.symlink(filename, linkname)
        self.assert_(os.path.lexists(linkname))
        self.assert_(not os.path.exists(linkname))
        delete(linkname)
        self.assert_(not os.path.exists(linkname))

        # test fifo
        args = ["mkfifo", filename]
        ret = subprocess.check_call(args)
        self.assertEqual(ret, 0)
        self.assert_(os.path.exists(filename))
        delete(filename)
        self.assert_(not os.path.exists(filename))



    def test_exe_exists(self):
        """Unit test for method exe_exists()"""
        tests = [ ("/bin/sh", True), \
            ("sh", True), \
            ("doesnotexist", False), \
            ("/bin/doesnotexist", False) ]
        for test in tests:
            self.assertEqual(exe_exists(test[0]), test[1])


    def test_getsize(self):
        """Unit test for method getsize()"""
        import tempfile

        # create regular file
        (handle, filename) = tempfile.mkstemp("regulartest")
        os.write(handle, "abcdefghij" * 12345)
        os.close(handle)
        output = subprocess.Popen(["du", "-h", filename], stdout=subprocess.PIPE).communicate()[0]
        output = output.replace("\n", "")
        du_size = output.split("\t")[0] + "B"
        print "output = '%s', size='%s'" % (output, du_size)
        du_bytes = self.__human_to_bytes(du_size)
        print output, du_size, du_bytes
        self.assertEqual(getsize(filename), du_bytes)

        # create a symlink
        linkname = '/tmp/bleachbitsymlinktest'
        os.symlink(filename, linkname)
        self.assert_(getsize(linkname) < 8192, "Symlink size is %d" % getsize(filename))
        delete(filename)

        # create sparse file
        (handle, filename) = tempfile.mkstemp("sparsetest")
        os.ftruncate(handle, 1024**2)
        os.close(handle)
        self.assertEqual(getsize(filename), 0)
        delete(filename)


    def test_is_broken_xdg_desktop(self):
        """Unit test for is_broken_xdg_desktop()"""
        menu_dirs = [ '/usr/share/applications', \
            '/usr/share/autostart', \
            '/usr/share/gnome/autostart', \
            '/usr/share/gnome/apps', \
            '/usr/share/mimelnk', \
            '/usr/share/applnk-redhat/', \
            '/usr/local/share/applications/' ]
        for dirname in menu_dirs:
            for filename in [fn for fn in children_in_directory(dirname, False) \
                if fn.endswith('.desktop')]:
                self.assert_(type(is_broken_xdg_desktop(filename) is bool))


    def test_wine_to_linux_path(self):
        """Unit test for wine_to_linux_path()"""
        tests = [ ("/home/foo/.wine", \
            "C:\\Program Files\\NSIS\\NSIS.exe", \
            "/home/foo/.wine/drive_c/Program Files/NSIS/NSIS.exe") ]
        for test in tests:
            self.assertEqual(wine_to_linux_path(test[0], test[1]), test[2])


    def test_OpenFiles(self):
        """Unit test for class OpenFiles"""
        import tempfile

        (handle, filename) = tempfile.mkstemp()
        self.assertEqual(openfiles.is_open(filename), True)

        f = os.fdopen(handle)
        f.close()
        openfiles.scan()
        self.assertEqual(openfiles.is_open(filename), False)

        os.unlink(filename)
        openfiles.scan()
        self.assertEqual(openfiles.is_open(filename), False)


if __name__ == '__main__':
    unittest.main()

