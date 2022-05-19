# Pyrenode

Copyright (c) 2020-2022 Antmicro

A rudimentary Python library to talk to Renode programatically.

## Version 1.0

Exposed telnet interface to Renode, allowing you to control it with the ``tell_renode`` command.

## Version 2.0

This version is using Robot remote keyword execution.

It imports all Renode keywords and enables them in the current namespace. See example.py for details.

### Installing

```
pip install git+https://github.com/antmicro/pyrenode.git
pip install git+https://github.com/antmicro/renode-run

```

## Running an example

```
./example.py
```

## TODO

* [ ] Better error handling
* [ ] Namespace organization
* [ ] Tutorial
* [ ] Tests
