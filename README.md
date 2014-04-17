Postgrepmgr
===========

This program helps postgres administrator
to easy build and manage PostgreSQL streaming
replication and failover.

Thist program works on Debian Wheezy, although
it should be easy to extend to other platforms.

To setup both master and slave you must make sure
your keys are copied on the destination servers
and your ssh forward agent variable is enabled.

To run this program you need to install fabric.
Fabric is best installed via pip.
```
$ pip install fabric
```
You may also opt to use your operating system’s
package manager, e.g.
```
$ apt-get install fabric
```
For further instruction you can visit the [fabric
documentation page](http://www.fabfile.org/).

Create a master with two replica
--------------------------------
This commands will create a 9.3 cluster
```
$ fab setup_master:10.0.0.1
$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.2
$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.3
```
For differnt PostgreSQL versions you'll have to instantiate
the `pg_version` variable. For instance you can create a 9.2
cluster by issuing:
```
$ fab setup_master:10.0.0.1,pg_version=9.2
$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.2,pg_version=9.2
$ fab setup_slave:pg_master=10.0.0.1,pg_slave=10.0.0.3,pg_version=9.2
```

Failover on a slave node after master failure
---------------------------------------------

Promote a new master
```
$ fab push_ssh_key:node=10.0.0.2
$ fab promote:10.0.0.2
```

Attach 10.0.0.3 to 10.0.0.2
```
$ fab setup_slave:pg_master=10.0.0.2,pg_slave=10.0.0.3
```

Attach 10.0.0.1 (old master) to 10.0.0.2
```
$ fab setup_slave:pg_master=10.0.0.2,pg_slave=10.0.0.1
```

For further info you can issue

```
$ fab help:<topic>
```

Where <topic> is a command name
