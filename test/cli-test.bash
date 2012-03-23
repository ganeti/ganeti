#!/bin/bash

export SCRIPTS=${TOP_BUILDDIR:-.}/scripts
export DAEMONS=${TOP_BUILDDIR:-.}/daemons

shelltest $SHELLTESTARGS \
  ${TOP_SRCDIR:-.}/test/gnt-*.test \
  -- --hide-successes
