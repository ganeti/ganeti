#!/bin/bash

export SCRIPTS=${TOP_BUILDDIR:-.}/scripts
export DAEMONS=${TOP_BUILDDIR:-.}/daemons

shelltest $SHELLTESTARGS \
  ${TOP_SRCDIR:-.}/test/py/legacy/{gnt,ganeti}-*.test \
  -- --hide-successes
