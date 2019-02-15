{-# LANGUAGE TemplateHaskell #-}
{-| CPUload data types

This module holds the definition of the data types describing the CPU
load according to information collected periodically from @/proc/stat@.

-}
{-

Copyright (C) 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}
module Ganeti.Cpu.Types
  ( CPUstat(..)
  , CPUavgload(..)
  ) where

import Ganeti.THH

-- | This is the format of the report produced by the cpu load
-- collector.
$(buildObject "CPUavgload" "cav"
  [ simpleField "cpu_number" [t| Int |]
  , simpleField "cpus"       [t| [Double] |]
  , simpleField "cpu_total"  [t| Double |]
  ])

-- | This is the format of the data parsed by the input file.
$(buildObject "CPUstat" "cs"
  [ simpleField "name"       [t| String |]
  , simpleField "user"       [t| Int |]
  , simpleField "nice"       [t| Int |]
  , simpleField "system"     [t| Int |]
  , simpleField "idle"       [t| Int |]
  , simpleField "iowait"     [t| Int |]
  , simpleField "irq"        [t| Int |]
  , simpleField "softirq"    [t| Int |]
  , simpleField "steal"      [t| Int |]
  , simpleField "guest"      [t| Int |]
  , simpleField "guest_nice" [t| Int |]
  ])
