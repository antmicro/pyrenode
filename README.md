# Pyrenode

Copyright (c) 2020-2022 Antmicro

A rudimentary Python library to talk to Renode using Python.

## Version 1.0

This is on the master branch. See README there for details. It was necessary for enabling demos like the [Google Colab integation](https://github.com/antmicro/tensorflow-arduino-examples).

## Version 2.0

This branch contains a seed for the "new" pyrenode, using Robot remote keyword execution.

### Installing

```
pip install robotframework
# and you need Renode too of course!
```

## Running an example

```
renode --robot-server-port 4444
```

And in another terminal:

```
./example.py
```

## TODO

* [ ] Function to run Renode programmatically
* [ ] Stop showing Renode window
* [ ] Better error handling
