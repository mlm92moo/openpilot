"""Updater state transitions that must stay safe across lifecycle changes."""
import os
import tempfile
import unittest
from unittest.mock import patch

from openpilot.system.updated import updated


class UpdaterReadyTests(unittest.TestCase):
  def _updater(self, branches, branch_by_path, commit_by_path):
    updater = object.__new__(updated.Updater)
    updater.branches = branches
    updater.get_branch = lambda path: branch_by_path[path]
    updater.get_commit_hash = lambda path=updated.OVERLAY_MERGED: commit_by_path[path]
    return updater

  def test_verified_finalized_update_only_offers_install(self):
    with tempfile.TemporaryDirectory() as root:
      basedir, finalized, merged = (os.path.join(root, name) for name in ("base", "final", "merged"))
      for path in (basedir, finalized, merged):
        os.mkdir(path)
      open(os.path.join(finalized, ".overlay_consistent"), "w").close()
      updater = self._updater({"fork": "new"}, {basedir: "fork", finalized: "fork", merged: "fork"},
                              {basedir: "old", finalized: "new", merged: "new"})
      with patch.object(updated.Updater, "target_branch", property(lambda _: "fork")), \
           patch.object(updated, "BASEDIR", basedir), patch.object(updated, "FINALIZED", finalized), \
           patch.object(updated, "OVERLAY_MERGED", merged):
        self.assertTrue(updater.update_ready)
        self.assertFalse(updater.update_available)

  def test_wrong_finalized_commit_is_not_installable(self):
    with tempfile.TemporaryDirectory() as root:
      basedir, finalized, merged = (os.path.join(root, name) for name in ("base", "final", "merged"))
      for path in (basedir, finalized, merged):
        os.mkdir(path)
      open(os.path.join(finalized, ".overlay_consistent"), "w").close()
      updater = self._updater({"fork": "new"}, {basedir: "fork", finalized: "fork", merged: "fork"},
                              {basedir: "old", finalized: "wrong", merged: "new"})
      with patch.object(updated.Updater, "target_branch", property(lambda _: "fork")), \
           patch.object(updated, "BASEDIR", basedir), patch.object(updated, "FINALIZED", finalized), \
           patch.object(updated, "OVERLAY_MERGED", merged):
        self.assertFalse(updater.update_ready)
        self.assertTrue(updater.update_available)
