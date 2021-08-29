#!/usr/bin/python3
#coding: utf-8

# Check Python version
import sys
if sys.hexversion < 0x03080000:
	sys.exit('You need at least Python 3.8. (You have %s.)' % sys.version.split()[0])

import argparse, codecs, configparser, os, re, subprocess

# Parse arguments

parser = argparse.ArgumentParser(description="Add or clone partial git submodules.")
parser.add_argument('-n', '--dry-run', dest='dryRun', default=False, action='store_true', help='Dry run (display git commands without executing them)')
parser.add_argument('-v', '--verbose', dest='verbose', default=False, action='store_true', help='Verbose (display git commands being run, and other info)')
subparsers = parser.add_subparsers(dest='command', metavar='command')

addCmdParser = subparsers.add_parser(
    'add',
    allow_abbrev = False,
    help = "Add a new partial submodule.",
    epilog = "All other options are passed through to the underlying git command.")
addCmdParser.add_argument('-b', dest='branch', help='Branch in the submodule repository to check out')
addCmdParser.add_argument('--name', dest='name', help='Logical name for the submodule')
addCmdParser.add_argument('repository', help='URL to the git repository to be added as a submodule')
addCmdParser.add_argument('path', help='Directory where the submodule will be checked out')

cloneCmdParser = subparsers.add_parser(
    'clone',
    allow_abbrev = False,
    help = "Clone partial submodules from .gitmodules.",
    epilog = "All other options are passed through to the underlying git command.")
cloneCmdParser.add_argument('paths', nargs='*', default=[], help='Submodule directory(ies) to clone (if unspecified, all submodules)')

args, gitPassthroughArgs = parser.parse_known_args()

if args.command is None:
    parser.print_help()
    sys.exit()

# Helper functions

def Git(*gitArgs):
    if args.verbose or args.dryRun:
        print('git ' + ' '.join(gitArgs))
    if args.dryRun:
        return
    cp = subprocess.run(('git',) + gitArgs)
    if cp.returncode != 0:
        sys.exit("Git command failed: git %s" % ' '.join(gitArgs))
    return cp

def ReadGitOutput(*gitArgs):
    # Not respecting verbose or dryRun here since this is just used for querying things, not modifying anything
    cp = subprocess.run(('git',) + gitArgs, stdout=subprocess.PIPE)
    if cp.returncode != 0:
        sys.exit(1)     # Git will have already printed an error to stderr
    return codecs.decode(cp.stdout, sys.stdout.encoding)

def CheckGitVersion(minVersion):
    if m := re.match(r'git version (\d+)\.(\d+)\.(\d+)', ReadGitOutput('--version')):
        gitVersion = tuple(int(m.group(i)) for i in range(1, 4))
    if gitVersion < minVersion:
        sys.exit("Git version is too old. You need at least %d.%d.%d, and you have %d.%d.%d." % (minVersion + gitVersion))

def GetWorktreeRoot():
    return os.path.abspath(ReadGitOutput('rev-parse', '--show-toplevel').strip())

def GetRepositoryRoot():
    return os.path.abspath(ReadGitOutput('rev-parse', '--git-dir').strip())

def ReadGitmodules(worktreeRoot):
    # Read the .gitmodules file
    gitmodulesConfig = configparser.ConfigParser(
        allow_no_value = True,
        default_section = None,
        inline_comment_prefixes = ('#', ';'),
        interpolation = None)
    if not gitmodulesConfig.read(os.path.join(worktreeRoot, '.gitmodules')):
        sys.exit("Couldn't parse .gitmodules!")
    if args.verbose:
        print("parsed %d submodules from .gitmodules" % len(gitmodulesConfig.sections()))

    # Build mapping tables
    gitmodules = argparse.Namespace(byName={}, byPath={})
    for section in gitmodulesConfig.sections():
        if m := re.match(r'submodule "(.*)"', section):
            name = m.group(1)
            contents = dict(gitmodulesConfig[section])
            contents['name'] = name
            gitmodules.byName[name] = contents
            if 'path' in contents:
                gitmodules.byPath[contents['path']] = contents
    return gitmodules

# Version 2.27.0 is needed for --filter and --sparse options on git clone
CheckGitVersion((2, 27, 0))

# Locate directories
worktreeRoot = GetWorktreeRoot()
repoRoot = GetRepositoryRoot()
if args.verbose:
    print("worktree root: %s\nrepo root: %s" % (worktreeRoot, repoRoot))

# Process commands

if args.dryRun:
    print("DRY RUN:")

if args.command == 'add':
    # TODO: do underlying git submodule add without cloning?
    # TODO: clone as partial, setup worktree
    print("Not yet implemented")

elif args.command == 'clone':
    # Load .gitmodules information
    gitmodules = ReadGitmodules(worktreeRoot)

    # Init the submodules - this ensures git config "submodule.foo" options are set up
    Git('submodule', 'init', *args.paths)

    if args.paths:
        # Make passed-in submodule paths relative to the worktree root
        submoduleRelPathsToProcess = [os.path.relpath(os.path.abspath(path), worktreeRoot)
                                        .replace('\\', '/')     # Git always uses forward slashes
                                        for path in args.paths]
    else:
        submoduleRelPathsToProcess = gitmodules.byPath.keys()

    submodulesSkipped = 0
    for submoduleRelPath in submoduleRelPathsToProcess:
        if submoduleRelPath not in gitmodules.byPath:
            sys.stderr.write("Couldn't find %s in .gitmodules! Skipping.\n" % submoduleRelPath)
            submodulesSkipped += 1
            continue
        submodule = gitmodules.byPath[submoduleRelPath]

        # Find the submodule's repo directory under the superproject's .git/modules/
        submoduleRepoRoot = os.path.join(repoRoot, 'modules', submodule['name'])
        if os.path.isdir(submoduleRepoRoot) and any(os.scandir(submoduleRepoRoot)):
            if args.verbose:
                print("%s submodule repo is nonempty; skipping" % submoduleRelPath)
            submodulesSkipped += 1
            continue

        # Find the submodule's worktree directory
        submoduleWorktreeRoot = os.path.join(worktreeRoot, os.path.normpath(submoduleRelPath))
        if os.path.isdir(submoduleWorktreeRoot) and any(os.scandir(submoduleWorktreeRoot)):
            sys.stderr.write("%s submodule worktree is nonempty! Skipping.\n" % submoduleRelPath)
            submodulesSkipped += 1
            continue

        # Create directories if necessary
        if not args.dryRun:
            os.makedirs(os.path.dirname(submoduleRepoRoot), exist_ok=True)
            os.makedirs(submoduleWorktreeRoot, exist_ok=True)   # Should have been created by 'git submodule init', but just make sure

        # Perform the partial clone!!!
        Git('clone',
            '--filter=blob:none',
            '--no-checkout',
            '--separate-git-dir', submoduleRepoRoot,
            *gitPassthroughArgs,
            submodule['url'],
            submoduleWorktreeRoot)

        # Apply sparse-checkout patterns in the submodule worktree
        # TODO: support "cone" mode?
        if sparseCheckoutPatterns := submodule.get('sparse-checkout'):
            Git('-C', submoduleWorktreeRoot, 'sparse-checkout', 'init')
            # Split patterns by whitespace - TODO: support quoted paths with embedded spaces etc?
            Git('-C', submoduleWorktreeRoot, 'sparse-checkout', 'set', *sparseCheckoutPatterns.split())
            print("Applied sparse-checkout patterns: %s" % sparseCheckoutPatterns)

        # Retrieve the commit sha1 that the submodule is supposed to be at
        treeInfo = ReadGitOutput('-C', worktreeRoot, 'ls-tree', 'HEAD', submoduleRelPath).split()
        if len(treeInfo) != 4:
            sys.exit("git ls-tree produced unexpected output:\n%s" % ' '.join(treeInfo))
        submoduleCommit = treeInfo[2]
        if args.verbose:
            print("%s submodule sha1 is %s" % (submoduleRelPath, submoduleCommit))

        # Checkout the submodule
        Git('-C', submoduleWorktreeRoot, 'checkout', '--detach', submoduleCommit)

        # Set core.worktree config on the submodule, as for some reason neither the clone nor the checkout does so
        # TODO: normal submodule checkouts in the primary worktree set this to a relative path,
        # but we're always setting an absolute path. Does it matter?
        Git('-C', submoduleWorktreeRoot, 'config', 'core.worktree',
            submoduleWorktreeRoot.replace('\\', '/'))       # Git always uses forward slashes

    print("Cloned %d submodules and skipped %d." %
            (len(submoduleRelPathsToProcess) - submodulesSkipped,
             submodulesSkipped))
