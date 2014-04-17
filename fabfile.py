"""
Setup master/slave streaming replication, and handle node
attachment/detachment from streaming cluster.

This script assume your pub keys are properly copied on the involved
servers and the ssh forwarding agent be active.
"""
import fabtools

from fabric.api import cd, env, local, parallel, serial
from fabric.api import put, run, settings, sudo, shell_env
from fabric.operations import prompt
from fabric.contrib import files, console


ETC_BASEDIR = "/etc/postgresql"
LIB_BASEDIR = "/var/lib/postgresql"

env.forward_agent = True
env.user = "root"


def _install_dependencies(what="pg", proxy=""):
    """ Configure the debian package system """

    post_path = "/etc/apt/sources.list.d/postgresql.list"
    pg_apt_key = "http://apt.postgresql.org/pub/repos/apt/ACCC4CF8.asc"

    packages = {
        "pg": [
            'postgresql-%s' % env.pg_version,
            'libpq-dev',
            'postgresql-server-dev-%s' % env.pg_version,
            'postgresql-contrib-%s' % env.pg_version,
            'libxslt-dev',
            'libxml2-dev',
            'libpam-dev',
            'libedit-dev',
        ],
        
        "repmgr": [
            'repmgr',
            'repmgr-dbg',
            'postgresql-%s-repmgr' % env.pg_version,
        ]
    }

    packages["all"] = packages["pg"] + packages["repmgr"]

    if not files.exists(post_path):
        put("conf/deb/postgresql.list", post_path)

    if proxy:
        with shell_env(http_proxy=proxy):
            run("wget --quiet -O - %s | apt-key add -" % pg_apt_key)
    else:
        run("wget --quiet -O - %s | apt-key add -" % pg_apt_key)

    run("apt-get update")
    run("apt-get -y install %s" % ' '.join(packages[what]))


def _setup_postgres(pg_master,
                    pg_slave,
                    pg_version,
                    cluster_name,
                    cluster_port,
                    standby,
                    proxy):
    """ Set up the postgres m/r """

    env.pg_master = pg_master
    env.pg_slave = pg_slave
    env.pg_version = pg_version
    env.cluster_name = cluster_name
    env.cluster_port = cluster_port

    if pg_version == "9.3":
        env.unix_directory = 'unix_socket_directories'
    else:
        env.unix_directory = 'unix_socket_directory'

    pg_local_dir = "conf/postgres"
    lib_dir = "%s/%s/%s" % (LIB_BASEDIR, pg_version, cluster_name)
    etc_dir = "%s/%s/%s" % (ETC_BASEDIR, pg_version, cluster_name)

    local_conf_file = "%s/postgresql.conf" % pg_local_dir
    pg_conf_file = "%s/postgresql.conf" % etc_dir

    local_hba_file = "%s/pg_hba.conf" % pg_local_dir
    pg_hba_file = "%s/pg_hba.conf" % etc_dir

    local_recovery_file = "%s/recovery.conf" % pg_local_dir
    pg_recovery_file = "%s/recovery.conf" % lib_dir

    _install_dependencies(proxy=proxy)

    # Upload the postgresql.conf file
    files.upload_template(
        local_conf_file,
        pg_conf_file,
        context=env,
        backup=False
    )

    if standby:
        # Drop default $PGDATA files and make a base backup by copying
        # the primary server's data directory to the standby server

        dbs = ""
        with settings(warn_only=True):
            dbs = run("su - postgres -c 'psql -l'")
        
        confirm = """This will destroy your $PGDATA files on host %s. \n
        Your DBMS is set up as follows:\n %s.\n
        Are you sure you want to continue?""" % (pg_slave, dbs)

        if console.confirm(confirm, default=False):
            with settings(warn_only=True):
                run("pg_ctlcluster %s %s stop" % (
                    pg_version, cluster_name))
                run("rm -rf %s/* " % lib_dir)

            run("pg_basebackup -D %s -U postgres -h %s" % (
                lib_dir, pg_master))

            # Upload recovery.conf file
            files.upload_template(
                local_recovery_file,
                pg_recovery_file,
                context=env,
                backup=False
            )

    run("chown -R postgres:postgres %s" % lib_dir)
    run("chown -R postgres:postgres %s" % etc_dir)

    run("/etc/init.d/postgresql stop")
    run("/etc/init.d/postgresql start")


def setup_master(pg_master,
                 pg_version="9.3",
                 cluster_name="main",
                 cluster_port="5432",
                 proxy=""):
    """ Setup the postgres master server """

    with settings(host_string=pg_master):
        _setup_postgres(
            pg_master,
            pg_slave="dummy",
            pg_version=pg_version,
            cluster_name=cluster_name,
            cluster_port=cluster_port,
            standby=False,
            proxy=proxy
        )


def setup_slave(pg_master,
                pg_slave,
                pg_version="9.3",
                cluster_name="main",
                cluster_port="5432",
                proxy=""):
    """ Setup the postgres slave server """

    # Copy the pg_hba record in the master to grant access to
    # slave. Take for granted that the master was set up before.
    with settings(host_string=pg_master):
        etc_dir = '%s/%s/%s' % (ETC_BASEDIR, pg_version, cluster_name)
        auth_record = "host replication postgres %s/32 trust\n" % (
            pg_slave)

        if not files.contains(
                "%s/pg_hba.conf" % etc_dir,
                auth_record):

            files.append(
                "%s/pg_hba.conf" % etc_dir,
                '\n%s' % auth_record)
            
            run("pg_ctlcluster %s %s reload" % (
                pg_version, cluster_name))

    with settings(host_string=pg_slave):
        _setup_postgres(
            pg_master,
            pg_slave,
            pg_version,
            cluster_name,
            cluster_port,
            standby=True,
            proxy=proxy
        )


def _gen_ssh_key(path="~/.ssh/id_rsa"):
    """ Generate the ssh key """

    run("ssh-keygen -t rsa -N '' -f %s" % path)
    
    
def _push_ssh_key(pg_node,
                  path="~/.ssh/id_rsa",
                  genkey=False):
    """ Push your ssh key on the desired node """

    if genkey:
        _gen_ssh_key(path)

    keyfile = run("cat %s.pub" % path)

    with settings(host_string=pg_node, warn_only=True):
        run("mkdir -p %s/.ssh && chmod 700 %s/.ssh" % (
            LIB_BASEDIR, LIB_BASEDIR))
        run("echo '%s' >> %s/.ssh/authorized_keys" % (
            keyfile, LIB_BASEDIR))
        run("chown -R postgres:postgres %s/.ssh" % LIB_BASEDIR)


def promote(pg_node,
            pg_version="9.3",
            cluster_name="main",
            putkey=False,
            genkey=False):
    """
    Promote a slave node in the cluster after a failover.

    After issuing this command it will be necessary to run
    setup_slave to attach any other potential slave 
    to the new master.
    """
    if putkey:
        _push_ssh_key(pg_node, genkey=genkey)
    
    lib_dir = "/usr/lib/postgresql/%s/bin" % pg_version

    with settings(host_string=pg_node, user="postgres"):
        run("%s/pg_ctl -D %s/%s/%s/ promote" % (
            lib_dir, LIB_BASEDIR, pg_version, cluster_name))


def push_ssh_key(pg_node,
                 path="~/.ssh/id_rsa",
                 genkey=False):
    """ Generate and put your ssh key on the desired node """

    _push_ssh_key(pg_node, path, genkey)


def help(topic="intro"):
    """ Print a brief explanation of the program """
    
    def intro():
        print "Postgrepmgr"
        print "==========="
        print
        print "This program help postgres administrator"
        print "to easy build and manage PostgreSQL streaming"
        print "replication and failover."
        print
        print "Thist program works on Debian Wheezy, although"
        print "it should be easy to extend to other platforms."
        print
        print "To setup both master and slave you must make sure"
        print "your keys are copied on the destination servers"
        print "and your ssh forward agent variable is enabled."
        print
        print "Tipical usage:"
        print 
        print "o Create a master with two replica (9.3)"
        print "----------------------------------------"
        print
        print "$ fab setup_master:10.0.0.1"
        print "$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.2"
        print "$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.3"
        print
        print "o Failover on a slave node after master failure"
        print "-----------------------------------------------"
        print
        print "Promote a new master"
        print "$ fab push_ssh_key:node=10.0.0.2"
        print "$ fab promote:10.0.0.2"
        print
        print "Attach 10.0.0.3 to 10.0.0.2"
        print "$ fab setup_slave:pg_master=10.0.0.2,pg_slave=10.0.0.3"
        print
        print "Attach 10.0.0.1 (old master) to 10.0.0.2"
        print "$ fab setup_slave:pg_master=10.0.0.2,pg_slave=10.0.0.1"
        print
        print "For further info you can issue"
        print
        print "$ fab help:<topic>"
        print
        print "Where <topic> is a command name"

    if topic == "intro":
        intro()

    elif topic == "setup_master":
        print "Setup a master node"
        print "==================="
        print
        print "To setup a master node you can issue:"
        print
        print "$ fab setup_master:pg_master=<ip master>"
        print
        print "Make sure you do not have postgres already"
        print "installed  and the /var/lib/postgresql and /etc/postgres"
        print "folders are not present on the destination server."
        
    elif topic == "setup_slave":
        print "Setup a slave node"
        print "=================="
        print
        print "To setup a slave node you can issue:"
        print
        print "$ fab setup_slaver:pg_master=<ip master>,pg_slave=<ip slave>"
        print
        print "Make sure you do not have postgres already"
        print "installed  and the /var/lib/postgresql and /etc/postgres"
        print "folders are not present on the destination server."

    elif topic == "promote":
        print "Promote"
        print "======="
        print
        print "This command promote a slave node to master"
        print "in case of failover."
        print
        print "Make sure you granted the access as postgres"
        print "on the remote server. You can use the command"
        print "push_ssh_key to ensure this."
        print
        print "Usage:"
        print
        print "$ fab promote:pg_node=<ip node>"

    elif topic == "push_ssh_key":
        print "Push ssh key"
        print "============"
        print
        print "This command put your ssh keys onto the desired node."
        print
        print "You have to make sure your user can access to the node with"
        print "postgres user credential because the 'promote' command can"
        print "only be issued by the postgres user."

    else:
        intro()
