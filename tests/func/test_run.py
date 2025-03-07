import filecmp
import logging
import os
import uuid
from pathlib import Path

import mock
import pytest

from dvc.dependency.base import DependencyIsStageFileError
from dvc.exceptions import ArgumentDuplicationError
from dvc.exceptions import CircularDependencyError
from dvc.exceptions import CyclicGraphError
from dvc.exceptions import OutputDuplicationError
from dvc.exceptions import OverlappingOutputPathsError
from dvc.exceptions import StagePathAsOutputError
from dvc.main import main
from dvc.output import OutputBase
from dvc.output.base import OutputIsStageFileError
from dvc.repo import Repo as DvcRepo
from dvc.stage import MissingDep
from dvc.stage import Stage
from dvc.stage import StageFileAlreadyExistsError
from dvc.stage import StageFileBadNameError
from dvc.stage import StagePathNotDirectoryError
from dvc.stage import StagePathNotFoundError
from dvc.stage import StagePathOutsideError
from dvc.system import System
from dvc.utils import file_md5
from dvc.utils.stage import load_stage_file
from tests.basic_env import TestDvc


class TestRun(TestDvc):
    def test(self):
        cmd = "python {} {} {}".format(self.CODE, self.FOO, "out")
        deps = [self.FOO, self.CODE]
        outs = [os.path.join(self.dvc.root_dir, "out")]
        outs_no_cache = []
        fname = "out.dvc"

        self.dvc.add(self.FOO)
        stage = self.dvc.run(
            cmd=cmd,
            deps=deps,
            outs=outs,
            outs_no_cache=outs_no_cache,
            fname=fname,
        )

        self.assertTrue(filecmp.cmp(self.FOO, "out", shallow=False))
        self.assertTrue(os.path.isfile(stage.path))
        self.assertEqual(stage.cmd, cmd)
        self.assertEqual(len(stage.deps), len(deps))
        self.assertEqual(len(stage.outs), len(outs + outs_no_cache))
        self.assertEqual(stage.outs[0].fspath, outs[0])
        self.assertEqual(stage.outs[0].checksum, file_md5(self.FOO)[0])
        self.assertTrue(stage.path, fname)

        with self.assertRaises(OutputDuplicationError):
            self.dvc.run(
                cmd=cmd,
                deps=deps,
                outs=outs,
                outs_no_cache=outs_no_cache,
                fname="duplicate" + fname,
            )


class TestRunEmpty(TestDvc):
    def test(self):
        self.dvc.run(
            cmd="", deps=[], outs=[], outs_no_cache=[], fname="empty.dvc",
        )


class TestRunMissingDep(TestDvc):
    def test(self):
        with self.assertRaises(MissingDep):
            self.dvc.run(
                cmd="",
                deps=["non-existing-dep"],
                outs=[],
                outs_no_cache=[],
                fname="empty.dvc",
            )


class TestRunNoExec(TestDvc):
    def test(self):
        self.dvc.run(
            cmd="python {} {} {}".format(self.CODE, self.FOO, "out"),
            no_exec=True,
        )
        self.assertFalse(os.path.exists("out"))


class TestRunCircularDependency(TestDvc):
    def test(self):
        with self.assertRaises(CircularDependencyError):
            self.dvc.run(
                cmd="",
                deps=[self.FOO],
                outs=[self.FOO],
                fname="circular-dependency.dvc",
            )

    def test_outs_no_cache(self):
        with self.assertRaises(CircularDependencyError):
            self.dvc.run(
                cmd="",
                deps=[self.FOO],
                outs_no_cache=[self.FOO],
                fname="circular-dependency.dvc",
            )

    def test_non_normalized_paths(self):
        with self.assertRaises(CircularDependencyError):
            self.dvc.run(
                cmd="",
                deps=["./foo"],
                outs=["foo"],
                fname="circular-dependency.dvc",
            )

    def test_graph(self):
        self.dvc.run(
            deps=[self.FOO], outs=["bar.txt"], cmd="echo bar > bar.txt"
        )

        self.dvc.run(
            deps=["bar.txt"], outs=["baz.txt"], cmd="echo baz > baz.txt"
        )

        with self.assertRaises(CyclicGraphError):
            self.dvc.run(
                deps=["baz.txt"], outs=[self.FOO], cmd="echo baz > foo"
            )


class TestRunDuplicatedArguments(TestDvc):
    def test(self):
        with self.assertRaises(ArgumentDuplicationError):
            self.dvc.run(
                cmd="",
                deps=[],
                outs=[self.FOO, self.FOO],
                fname="circular-dependency.dvc",
            )

    def test_outs_no_cache(self):
        with self.assertRaises(ArgumentDuplicationError):
            self.dvc.run(
                cmd="",
                outs=[self.FOO],
                outs_no_cache=[self.FOO],
                fname="circular-dependency.dvc",
            )

    def test_non_normalized_paths(self):
        with self.assertRaises(ArgumentDuplicationError):
            self.dvc.run(
                cmd="",
                deps=[],
                outs=["foo", "./foo"],
                fname="circular-dependency.dvc",
            )


class TestRunStageInsideOutput(TestDvc):
    def test_cwd(self):
        self.dvc.run(cmd="", deps=[], outs=[self.DATA_DIR])

        with self.assertRaises(StagePathAsOutputError):
            self.dvc.run(
                cmd="", fname=os.path.join(self.DATA_DIR, "inside-cwd.dvc")
            )

    def test_file_name(self):
        self.dvc.run(cmd="", deps=[], outs=[self.DATA_DIR])

        with self.assertRaises(StagePathAsOutputError):
            self.dvc.run(
                cmd="",
                outs=[self.FOO],
                fname=os.path.join(self.DATA_DIR, "inside-cwd.dvc"),
            )


class TestRunBadCwd(TestDvc):
    def test(self):
        with self.assertRaises(StagePathOutsideError):
            self.dvc.run(cmd="", wdir=self.mkdtemp())

    def test_same_prefix(self):
        with self.assertRaises(StagePathOutsideError):
            path = "{}-{}".format(self._root_dir, uuid.uuid4())
            os.mkdir(path)
            self.dvc.run(cmd="", wdir=path)


class TestRunBadWdir(TestDvc):
    def test(self):
        with self.assertRaises(StagePathOutsideError):
            self.dvc.run(cmd="", wdir=self.mkdtemp())

    def test_same_prefix(self):
        with self.assertRaises(StagePathOutsideError):
            path = "{}-{}".format(self._root_dir, uuid.uuid4())
            os.mkdir(path)
            self.dvc.run(cmd="", wdir=path)

    def test_not_found(self):
        with self.assertRaises(StagePathNotFoundError):
            path = os.path.join(self._root_dir, str(uuid.uuid4()))
            self.dvc.run(cmd="", wdir=path)

    def test_not_dir(self):
        with self.assertRaises(StagePathNotDirectoryError):
            path = os.path.join(self._root_dir, str(uuid.uuid4()))
            os.mkdir(path)
            path = os.path.join(path, str(uuid.uuid4()))
            open(path, "a").close()
            self.dvc.run(cmd="", wdir=path)


class TestRunBadName(TestDvc):
    def test(self):
        with self.assertRaises(StagePathOutsideError):
            self.dvc.run(
                cmd="",
                fname=os.path.join(
                    self.mkdtemp(), self.FOO + Stage.STAGE_FILE_SUFFIX
                ),
            )

    def test_same_prefix(self):
        with self.assertRaises(StagePathOutsideError):
            path = "{}-{}".format(self._root_dir, uuid.uuid4())
            os.mkdir(path)
            self.dvc.run(
                cmd="",
                fname=os.path.join(path, self.FOO + Stage.STAGE_FILE_SUFFIX),
            )

    def test_not_found(self):
        with self.assertRaises(StagePathNotFoundError):
            path = os.path.join(self._root_dir, str(uuid.uuid4()))
            self.dvc.run(
                cmd="",
                fname=os.path.join(path, self.FOO + Stage.STAGE_FILE_SUFFIX),
            )


class TestRunRemoveOuts(TestDvc):
    def test(self):
        with open(self.CODE, "w+") as fobj:
            fobj.write("import sys\n")
            fobj.write("import os\n")
            fobj.write("if os.path.exists(sys.argv[1]):\n")
            fobj.write("    sys.exit(1)\n")
            fobj.write("open(sys.argv[1], 'w+').close()\n")

        self.dvc.run(
            deps=[self.CODE],
            outs=[self.FOO],
            cmd="python {} {}".format(self.CODE, self.FOO),
        )


class TestRunUnprotectOutsCopy(TestDvc):
    def test(self):
        with open(self.CODE, "w+") as fobj:
            fobj.write("import sys\n")
            fobj.write("with open(sys.argv[1], 'a+') as fobj:\n")
            fobj.write("    fobj.write('foo')\n")

        ret = main(["config", "cache.type", "copy"])
        self.assertEqual(ret, 0)

        ret = main(
            [
                "run",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)
        self.assertTrue(os.access(self.FOO, os.W_OK))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")

        ret = main(
            [
                "run",
                "--overwrite-dvcfile",
                "--ignore-build-cache",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)
        self.assertTrue(os.access(self.FOO, os.W_OK))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")


class TestRunUnprotectOutsSymlink(TestDvc):
    def test(self):
        with open(self.CODE, "w+") as fobj:
            fobj.write("import sys\n")
            fobj.write("import os\n")
            fobj.write("with open(sys.argv[1], 'a+') as fobj:\n")
            fobj.write("    fobj.write('foo')\n")

        ret = main(["config", "cache.type", "symlink"])
        self.assertEqual(ret, 0)

        self.assertEqual(ret, 0)
        ret = main(
            [
                "run",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)

        if os.name == "nt":
            # NOTE: Windows symlink perms don't propagate to the target
            self.assertTrue(os.access(self.FOO, os.W_OK))
        else:
            self.assertFalse(os.access(self.FOO, os.W_OK))

        self.assertTrue(System.is_symlink(self.FOO))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")

        ret = main(
            [
                "run",
                "--overwrite-dvcfile",
                "--ignore-build-cache",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)

        if os.name == "nt":
            # NOTE: Windows symlink perms don't propagate to the target
            self.assertTrue(os.access(self.FOO, os.W_OK))
        else:
            self.assertFalse(os.access(self.FOO, os.W_OK))

        self.assertTrue(System.is_symlink(self.FOO))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")


class TestRunUnprotectOutsHardlink(TestDvc):
    def test(self):
        with open(self.CODE, "w+") as fobj:
            fobj.write("import sys\n")
            fobj.write("import os\n")
            fobj.write("with open(sys.argv[1], 'a+') as fobj:\n")
            fobj.write("    fobj.write('foo')\n")

        ret = main(["config", "cache.type", "hardlink"])
        self.assertEqual(ret, 0)

        self.assertEqual(ret, 0)
        ret = main(
            [
                "run",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)
        self.assertFalse(os.access(self.FOO, os.W_OK))
        self.assertTrue(System.is_hardlink(self.FOO))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")

        ret = main(
            [
                "run",
                "--overwrite-dvcfile",
                "--ignore-build-cache",
                "-d",
                self.CODE,
                "-o",
                self.FOO,
                "python",
                self.CODE,
                self.FOO,
            ]
        )
        self.assertEqual(ret, 0)
        self.assertFalse(os.access(self.FOO, os.W_OK))
        self.assertTrue(System.is_hardlink(self.FOO))
        with open(self.FOO, "r") as fd:
            self.assertEqual(fd.read(), "foo")


class TestCmdRunOverwrite(TestDvc):
    def test(self):
        # NOTE: using sleep() is a workaround  for filesystems
        # with low mtime resolution. We have to use mtime since
        # comparing mtime's is the only way to check that the stage
        # file didn't change(size and inode in the first test down
        # below don't change).
        import time

        ret = main(
            [
                "run",
                "-d",
                self.FOO,
                "-d",
                self.CODE,
                "-o",
                "out",
                "-f",
                "out.dvc",
                "python",
                self.CODE,
                self.FOO,
                "out",
            ]
        )
        self.assertEqual(ret, 0)

        stage_mtime = os.path.getmtime("out.dvc")

        time.sleep(1)

        ret = main(
            [
                "run",
                "-d",
                self.FOO,
                "-d",
                self.CODE,
                "-o",
                "out",
                "-f",
                "out.dvc",
                "python",
                self.CODE,
                self.FOO,
                "out",
            ]
        )
        self.assertEqual(ret, 0)

        # NOTE: check that dvcfile was NOT overwritten
        self.assertEqual(stage_mtime, os.path.getmtime("out.dvc"))
        stage_mtime = os.path.getmtime("out.dvc")

        time.sleep(1)

        ret = main(
            [
                "run",
                "-d",
                self.FOO,
                "-d",
                self.CODE,
                "--overwrite-dvcfile",
                "--ignore-build-cache",
                "-o",
                "out",
                "-f",
                "out.dvc",
                "python",
                self.CODE,
                self.FOO,
                "out",
            ]
        )
        self.assertEqual(ret, 0)

        # NOTE: check that dvcfile was overwritten
        self.assertNotEqual(stage_mtime, os.path.getmtime("out.dvc"))
        stage_mtime = os.path.getmtime("out.dvc")

        time.sleep(1)

        ret = main(
            ["run", "--overwrite-dvcfile", "-f", "out.dvc", "-d", self.BAR]
        )
        self.assertEqual(ret, 0)

        # NOTE: check that dvcfile was overwritten
        self.assertNotEqual(stage_mtime, os.path.getmtime("out.dvc"))


class TestCmdRunCliMetrics(TestDvc):
    def test_cached(self):
        ret = main(["run", "-m", "metrics.txt", "echo test > metrics.txt"])
        self.assertEqual(ret, 0)
        with open("metrics.txt", "r") as fd:
            self.assertEqual(fd.read().rstrip(), "test")

    def test_not_cached(self):
        ret = main(["run", "-M", "metrics.txt", "echo test > metrics.txt"])
        self.assertEqual(ret, 0)
        with open("metrics.txt", "r") as fd:
            self.assertEqual(fd.read().rstrip(), "test")


class TestCmdRunWorkingDirectory(TestDvc):
    def test_default_wdir_is_not_written(self):
        stage = self.dvc.run(
            cmd="echo test > {}".format(self.FOO), outs=[self.FOO], wdir="."
        )
        d = load_stage_file(stage.relpath)
        self.assertNotIn(Stage.PARAM_WDIR, d.keys())

        stage = self.dvc.run(
            cmd="echo test > {}".format(self.BAR), outs=[self.BAR]
        )
        d = load_stage_file(stage.relpath)
        self.assertNotIn(Stage.PARAM_WDIR, d.keys())

    def test_fname_changes_path_and_wdir(self):
        dname = "dir"
        os.mkdir(os.path.join(self._root_dir, dname))
        foo = os.path.join(dname, self.FOO)
        fname = os.path.join(dname, "stage" + Stage.STAGE_FILE_SUFFIX)
        stage = self.dvc.run(
            cmd="echo test > {}".format(foo), outs=[foo], fname=fname
        )
        self.assertEqual(stage.wdir, os.path.realpath(self._root_dir))
        self.assertEqual(
            stage.path, os.path.join(os.path.realpath(self._root_dir), fname)
        )

        # Check that it is dumped properly (relative to fname)
        d = load_stage_file(stage.relpath)
        self.assertEqual(d[Stage.PARAM_WDIR], "..")


def test_rerun_deterministic(tmp_dir, run_copy):
    tmp_dir.gen("foo", "foo content")

    assert run_copy("foo", "out") is not None
    assert run_copy("foo", "out") is None


def test_rerun_deterministic_ignore_cache(tmp_dir, run_copy):
    tmp_dir.gen("foo", "foo content")

    assert run_copy("foo", "out") is not None
    assert run_copy("foo", "out", ignore_build_cache=True) is not None


def test_rerun_callback(dvc):
    def run_callback():
        return dvc.run(
            cmd=("echo content > out"), outs=["out"], deps=[], overwrite=False
        )

    assert run_callback() is not None

    with mock.patch("dvc.prompt.confirm", return_value=True):
        assert run_callback() is not None


def test_rerun_changed_dep(tmp_dir, run_copy):
    tmp_dir.gen("foo", "foo content")
    assert run_copy("foo", "out") is not None

    tmp_dir.gen("foo", "changed content")
    with pytest.raises(StageFileAlreadyExistsError):
        run_copy("foo", "out", overwrite=False)


def test_rerun_changed_stage(tmp_dir, run_copy):
    tmp_dir.gen("foo", "foo content")
    assert run_copy("foo", "out") is not None

    tmp_dir.gen("bar", "bar content")
    with pytest.raises(StageFileAlreadyExistsError):
        run_copy("bar", "out", overwrite=False)


def test_rerun_changed_out(tmp_dir, run_copy):
    tmp_dir.gen("foo", "foo content")
    assert run_copy("foo", "out") is not None

    Path("out").write_text("modification")
    with pytest.raises(StageFileAlreadyExistsError):
        run_copy("foo", "out", overwrite=False)


class TestRunCommit(TestDvc):
    def test(self):
        fname = "test"
        ret = main(
            ["run", "-o", fname, "--no-commit", "echo", "test", ">", fname]
        )
        self.assertEqual(ret, 0)
        self.assertTrue(os.path.isfile(fname))
        self.assertFalse(os.path.exists(self.dvc.cache.local.cache_dir))

        ret = main(["commit", fname + ".dvc"])
        self.assertEqual(ret, 0)
        self.assertTrue(os.path.isfile(fname))
        self.assertEqual(len(os.listdir(self.dvc.cache.local.cache_dir)), 1)


class TestRunPersist(TestDvc):
    @property
    def outs_command(self):
        raise NotImplementedError

    def _test(self):
        file = "file.txt"
        file_content = "content"
        stage_file = file + Stage.STAGE_FILE_SUFFIX

        self.run_command(file, file_content)
        self.stage_should_contain_persist_flag(stage_file)

        self.should_append_upon_repro(file, stage_file)

        self.should_remove_persistent_outs(file, stage_file)

    def run_command(self, file, file_content):
        ret = main(
            [
                "run",
                self.outs_command,
                file,
                "echo {} >> {}".format(file_content, file),
            ]
        )
        self.assertEqual(0, ret)

    def stage_should_contain_persist_flag(self, stage_file):
        stage_file_content = load_stage_file(stage_file)
        self.assertEqual(
            True, stage_file_content["outs"][0][OutputBase.PARAM_PERSIST]
        )

    def should_append_upon_repro(self, file, stage_file):
        ret = main(["repro", stage_file])
        self.assertEqual(0, ret)

        with open(file, "r") as fobj:
            lines = fobj.readlines()
        self.assertEqual(2, len(lines))

    def should_remove_persistent_outs(self, file, stage_file):
        ret = main(["remove", stage_file])
        self.assertEqual(0, ret)

        self.assertFalse(os.path.exists(file))


class TestRunPersistOuts(TestRunPersist):
    @property
    def outs_command(self):
        return "--outs-persist"

    def test(self):
        self._test()


class TestRunPersistOutsNoCache(TestRunPersist):
    @property
    def outs_command(self):
        return "--outs-persist-no-cache"

    def test(self):
        self._test()


class TestShouldRaiseOnOverlappingOutputPaths(TestDvc):
    def test(self):
        ret = main(["add", self.DATA_DIR])
        self.assertEqual(0, ret)

        with self.assertRaises(OverlappingOutputPathsError) as err:
            self.dvc.run(
                outs=[self.DATA], cmd="echo data >> {}".format(self.DATA)
            )
        error_output = str(err.exception)

        data_dir_stage = self.DATA_DIR + Stage.STAGE_FILE_SUFFIX
        data_stage = os.path.basename(self.DATA) + Stage.STAGE_FILE_SUFFIX

        self.assertIn("Paths for outs:\n", error_output)
        self.assertIn(
            "\n'{}'('{}')\n".format(self.DATA_DIR, data_dir_stage),
            error_output,
        )
        self.assertIn(
            "\n'{}'('{}')\n".format(self.DATA, data_stage), error_output
        )
        self.assertIn(
            "\noverlap. To avoid unpredictable behaviour, rerun "
            "command with non overlapping outs paths.",
            error_output,
        )


class TestRerunWithSameOutputs(TestDvc):
    def _read_content_only(self, path):
        with open(path, "r") as fobj:
            return [line.rstrip() for line in fobj]

    @property
    def _outs_command(self):
        raise NotImplementedError

    def _run_twice_with_same_outputs(self):
        ret = main(
            [
                "run",
                "--outs",
                self.FOO,
                "echo {} > {}".format(self.FOO_CONTENTS, self.FOO),
            ]
        )
        self.assertEqual(0, ret)

        output_file_content = self._read_content_only(self.FOO)
        self.assertEqual([self.FOO_CONTENTS], output_file_content)

        ret = main(
            [
                "run",
                self._outs_command,
                self.FOO,
                "--overwrite-dvcfile",
                "echo {} >> {}".format(self.BAR_CONTENTS, self.FOO),
            ]
        )
        self.assertEqual(0, ret)


class TestNewRunShouldRemoveOutsOnNoPersist(TestRerunWithSameOutputs):
    def test(self):
        self._run_twice_with_same_outputs()

        output_file_content = self._read_content_only(self.FOO)
        self.assertEqual([self.BAR_CONTENTS], output_file_content)

    @property
    def _outs_command(self):
        return "--outs"


class TestNewRunShouldNotRemoveOutsOnPersist(TestRerunWithSameOutputs):
    def test(self):
        self._run_twice_with_same_outputs()

        output_file_content = self._read_content_only(self.FOO)
        self.assertEqual(
            [self.FOO_CONTENTS, self.BAR_CONTENTS], output_file_content
        )

    @property
    def _outs_command(self):
        return "--outs-persist"


class TestShouldNotCheckoutUponCorruptedLocalHardlinkCache(TestDvc):
    def setUp(self):
        super().setUp()
        ret = main(["config", "cache.type", "hardlink"])
        self.assertEqual(ret, 0)
        self.dvc = DvcRepo(".")

    def test(self):
        cmd = "python {} {} {}".format(self.CODE, self.FOO, self.BAR)
        stage = self.dvc.run(deps=[self.FOO], outs=[self.BAR], cmd=cmd)

        os.chmod(self.BAR, 0o644)
        with open(self.BAR, "w") as fd:
            fd.write("corrupting the output cache")

        patch_checkout = mock.patch.object(
            stage.outs[0], "checkout", wraps=stage.outs[0].checkout
        )
        patch_run = mock.patch.object(stage, "_run", wraps=stage._run)

        with self.dvc.lock, self.dvc.state:
            with patch_checkout as mock_checkout:
                with patch_run as mock_run:
                    stage.run()

                    mock_run.assert_called_once()
                    mock_checkout.assert_not_called()


class TestPersistentOutput(TestDvc):
    def test_ignore_build_cache(self):
        warning = "Build cache is ignored when persisting outputs."

        with open("immutable", "w") as fobj:
            fobj.write("1")

        cmd = [
            "run",
            "--overwrite-dvcfile",
            "--deps",
            "immutable",
            "--outs-persist",
            "greetings",
            "echo hello>>greetings",
        ]

        with self._caplog.at_level(logging.WARNING, logger="dvc"):
            assert main(cmd) == 0
            assert warning not in self._caplog.text

            assert main(cmd) == 0
            assert warning in self._caplog.text

        # Even if the "immutable" dependency didn't change
        # it should run the command again, as it is "ignoring build cache"
        with open("greetings", "r") as fobj:
            assert "hello\nhello\n" == fobj.read()


def test_bad_stage_fname(tmp_dir, dvc, run_copy):
    tmp_dir.dvc_gen("foo", "foo content")

    with pytest.raises(StageFileBadNameError):
        # fname should end with .dvc
        run_copy("foo", "foo_copy", fname="out_stage")

    # Check that command hasn't been run
    assert not (tmp_dir / "foo_copy").exists()


def test_should_raise_on_stage_dependency(run_copy):
    with pytest.raises(DependencyIsStageFileError):
        run_copy("name.dvc", "stage_copy")


def test_should_raise_on_stage_output(tmp_dir, dvc, run_copy):
    tmp_dir.dvc_gen("foo", "foo content")

    with pytest.raises(OutputIsStageFileError):
        run_copy("foo", "name.dvc")
