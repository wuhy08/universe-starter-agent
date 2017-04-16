import argparse
import os
import sys
from six.moves import shlex_quote

parser = argparse.ArgumentParser(description="Run commands")
parser.add_argument('-w', '--num-workers', default=1, type=int,
                    help="Number of workers")
parser.add_argument('-r', '--remotes', default=None,
                    help='The address of pre-existing VNC servers and '
                         'rewarders to use (e.g. -r vnc://localhost:5900+15900,vnc://localhost:5901+15901).')
parser.add_argument('-e', '--env-id', type=str, default="PongDeterministic-v3",
                    help="Environment id")
parser.add_argument('-l', '--log-dir', type=str, default="/tmp/pong",
                    help="Log directory path")
parser.add_argument('-n', '--dry-run', action='store_true',
                    help="Print out commands rather than executing them")
parser.add_argument('-m', '--mode', type=str, default='tmux',
                    help="tmux: run workers in a tmux session. nohup: run workers with nohup. child: run workers as child processes")

# Add visualise tag
parser.add_argument('--visualise', action='store_true',
                    help="Visualise the gym environment by running env.render() between each timestep")

parser.add_argument('--sudo', action='store_true',
                    help="Give sudo access in tmux")

parser.add_argument('--prints', action='store_true',
                    help="only print to file")

def new_cmd(session, name, cmd, mode, logdir, shell, sudo=False):
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(shlex_quote(str(v)) for v in cmd)
    sudo_str = "sudo" if sudo else ""
    if mode == 'tmux':
        return name, "{} tmux send-keys -t {}:{} {} Enter".format(sudo_str, session, name, shlex_quote(cmd))
    elif mode == 'child':
        return name, "{} {} >{}/{}.{}.out 2>&1 & echo kill $! >>{}/kill.sh".format(sudo_str, cmd, logdir, session, name, logdir)
    elif mode == 'nohup':
        return name, "{} nohup {} -c {} >{}/{}.{}.out 2>&1 & echo kill $! >>{}/kill.sh".format(sudo_str, shell, shlex_quote(cmd), logdir, session, name, logdir)


def create_commands(session, num_workers, remotes, env_id, logdir, shell='bash', mode='tmux', visualise=False, sudo=False):
    # for launching the TF workers and for launching tensorboard
    base_cmd = ['sudo'] if sudo else []
    base_cmd += [
        'CUDA_VISIBLE_DEVICES=',
        sys.executable, 'worker.py',
        '--log-dir', logdir,
        '--env-id', env_id,
        '--num-workers', str(num_workers)]

    if visualise:
        base_cmd += ['--visualise']

    if remotes is None:
        remotes = ["1"] * num_workers
    else:
        remotes = remotes.split(',')
        assert len(remotes) == num_workers

    cmds_map = [new_cmd(session, "ps", base_cmd + ["--job-name", "ps"], mode, logdir, shell, sudo=sudo)]
    for i in range(num_workers):
        cmds_map += [new_cmd(session,
            "w-%d" % i, base_cmd + ["--job-name", "worker", "--task", str(i), "--remotes", remotes[i]], mode, logdir, shell, sudo=sudo)]

    cmds_map += [new_cmd(session, "tb", ["tensorboard", "--logdir", logdir, "--port", "12345"], mode, logdir, shell, sudo=sudo)]
    if mode == 'tmux':
        cmds_map += [new_cmd(session, "htop", ["htop"], mode, logdir, shell, sudo=sudo)]

    windows = [v[0] for v in cmds_map]

    notes = []
    cmds = [
        "mkdir -p {}".format(logdir),
        "echo {} {} > {}/cmd.sh".format(sys.executable, ' '.join([shlex_quote(arg) for arg in sys.argv if arg != '-n']), logdir),
    ]
    if mode == 'nohup' or mode == 'child':
        cmds += ["echo '#!/bin/sh' >{}/kill.sh".format(logdir)]
        notes += ["Run `source {}/kill.sh` to kill the job".format(logdir)]
    if mode == 'tmux':
        notes += ["Use `tmux attach -t {}` to watch process output".format(session)]
        notes += ["Use `tmux kill-session -t {}` to kill the job".format(session)]
    else:
        notes += ["Use `tail -f {}/*.out` to watch process output".format(logdir)]
    notes += ["Point your browser to http://localhost:12345 to see Tensorboard"]

    sudo_str = "sudo" if sudo else ""
    if mode == 'tmux':
        cmds += [
        "{} kill $( lsof -i:12345 -t ) > /dev/null 2>&1".format(sudo_str),  # kill any process using tensorboard's port
        "{} kill $( lsof -i:12222-{} -t ) > /dev/null 2>&1".format(sudo_str, num_workers+12222), # kill any processes using ps / worker ports
        "{} tmux kill-session -t {}".format(sudo_str, session),
        "{} tmux new-session -s {} -n {} -d {}".format(sudo_str, session, windows[0], shell)
        ]
        for w in windows[1:]:
            cmds += ["{} tmux new-window -t {} -n {} {}".format(sudo_str, session, w, shell)]
        cmds += ["sleep 1"]
    for window, cmd in cmds_map:
        cmds += [cmd]

    return cmds, notes


def run():
    args = parser.parse_args()
    cmds, notes = create_commands("a3c", args.num_workers, args.remotes, args.env_id, args.log_dir, mode=args.mode, visualise=args.visualise, sudo=args.sudo)
    if args.dry_run:
        print("Dry-run mode due to -n flag, otherwise the following commands would be executed:")
    else:
        print("Executing the following commands:")
    print("\n".join(cmds))
    print("")
    if args.prints:
        print("only print the command line above to file")
        with open('cmds', 'w') as f:
            for cmd in cmds:
                f.write('{}\n'.format(cmd))  # python will convert \n to os.linesep
    else:
        if not args.dry_run:
            if args.mode == "tmux":
                os.environ["TMUX"] = ""
            os.system("\n".join(cmds))
    print('\n'.join(notes))


if __name__ == "__main__":
    run()
