# encoding: utf-8
from __future__ import division, print_function, unicode_literals

"""
Push to Git — one-shot save + commit + push for the current font.

Adds "Save, Commit & Push" to the File menu (Ctrl-Cmd-S). Saves the frontmost
font, then commits and pushes on a background thread so Glyphs never blocks.
A notification reports the result. Change the shortcut anytime in System
Settings > Keyboard > Keyboard Shortcuts > App Shortcuts.
"""

import objc
import os
import subprocess
import threading
import datetime
from GlyphsApp import Glyphs, FILE_MENU
from GlyphsApp.plugins import GeneralPlugin
from AppKit import (
    NSMenuItem,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
)
from Foundation import NSOperationQueue

VERSION = "1.1"
COMMIT_WHOLE_REPO = False  # False: only the .glyphs file; True: git add -A
GIT_TIMEOUT = 120  # seconds before a hung push gives up
LOGFILE = os.path.expanduser("~/Library/Logs/PushToGit.log")


class PushToGit(GeneralPlugin):

    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize({"en": "Save, Commit & Push"})
        self.busy = False

    @objc.python_method
    def start(self):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self.name, self.pushToGit_, "s"
        )
        item.setKeyEquivalentModifierMask_(
            NSEventModifierFlagCommand | NSEventModifierFlagControl
        )
        item.setTarget_(self)
        Glyphs.menu[FILE_MENU].append(item)
        self.log("---- Push to Git v%s loaded ----" % VERSION)

    def pushToGit_(self, sender):
        font = Glyphs.font
        if font is None:
            self.notify("Push to Git", "No font open.")
            return
        if self.busy:
            self.notify("Push to Git", "A push is already running.")
            return

        try:
            doc = font.parent
            if doc is not None and doc.respondsToSelector_("saveDocument:"):
                doc.saveDocument_(None)
            else:
                font.save()
        except Exception as e:
            self.notify("Push to Git failed", "Could not save: %s" % e)
            return

        filepath = font.filepath
        if not filepath:
            self.notify("Push to Git", "Save the file somewhere first.")
            return

        title = font.familyName or os.path.basename(filepath)
        self.busy = True
        thread = threading.Thread(
            target=self.commitAndPush, args=(filepath, title), name="PushToGit"
        )
        thread.daemon = True
        thread.start()

    @objc.python_method
    def commitAndPush(self, filepath, title):
        try:
            workdir = os.path.dirname(filepath)
            git = "/usr/bin/git"

            ok, root = self.git(git, workdir, "rev-parse", "--show-toplevel")
            if not ok:
                self.notify("Push to Git failed", "%s is not in a git repository." % os.path.basename(filepath))
                return

            if COMMIT_WHOLE_REPO:
                ok, out = self.git(git, workdir, "add", "-A")
            else:
                ok, out = self.git(git, workdir, "add", "--", filepath)
            if not ok:
                self.notify("Push to Git failed", "git add: %s" % out)
                return

            committed = False
            ok, out = self.git(git, workdir, "diff", "--cached", "--quiet")
            if not ok:  # staged changes exist
                message = "%s — %s" % (title, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
                ok, out = self.git(git, workdir, "commit", "-m", message)
                if not ok:
                    self.notify("Push to Git failed", "git commit: %s" % out)
                    return
                committed = True

            # a CI bot (or another machine) may have moved the remote since the
            # last pull; rebase our commits on top, then push. two attempts in
            # case the remote moves again mid-push.
            pushed = False
            for attempt in range(2):
                ok, out = self.git(git, workdir, "pull", "--rebase", "--autostash", "origin")
                if not ok:
                    self.git(git, workdir, "rebase", "--abort")
                    self.notify(
                        "Push to Git failed",
                        "Remote has conflicting changes — pull and resolve manually. %s" % out.strip()[-140:],
                    )
                    return
                ok, out = self.git(git, workdir, "push", "origin", "HEAD")
                if ok:
                    pushed = True
                    break
            if not pushed:
                self.notify("Push to Git failed", "git push: %s" % out.strip()[-180:])
                return

            if committed:
                self.notify("Pushed ✓", "%s committed and pushed." % title)
            elif "up-to-date" in out or "up to date" in out:
                self.notify("Push to Git", "No changes — already up to date.")
            else:
                self.notify("Pushed ✓", "Pending commits pushed (no new changes).")
        except Exception as e:
            self.notify("Push to Git failed", str(e))
        finally:
            self.busy = False

    @objc.python_method
    def git(self, git, workdir, *args):
        """Returns (success, combined output)."""
        try:
            proc = subprocess.run(
                [git, "-C", workdir] + list(args),
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            ok = proc.returncode == 0
            self.log("git %s -> %d %s" % (" ".join(args), proc.returncode, out.strip()[:300]))
            return ok, out
        except subprocess.TimeoutExpired:
            self.log("git %s -> TIMEOUT" % " ".join(args))
            return False, "timed out after %ds" % GIT_TIMEOUT
        except Exception as e:
            self.log("git %s -> EXC %s" % (" ".join(args), e))
            return False, str(e)

    @objc.python_method
    def log(self, line):
        try:
            with open(LOGFILE, "a") as f:
                f.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), line))
        except Exception:
            pass

    @objc.python_method
    def notify(self, notificationTitle, message):
        self.log("NOTIFY: %s — %s" % (notificationTitle, message))

        def show():
            Glyphs.showNotification(notificationTitle, message)
        NSOperationQueue.mainQueue().addOperationWithBlock_(show)

    @objc.python_method
    def __file__(self):
        return __file__
