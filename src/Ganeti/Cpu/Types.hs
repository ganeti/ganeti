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
  , emptyCPUavgload
  ) where

import Ganeti.THH

-- | This is the format of the report produced by the cpu load
-- collector.
$(buildObject "CPUavgload" "cav"
  [ simpleField "cpu_number" [t| Int |]
  , simpleField "cpus"       [t| [Double] |]
  , simpleField "cpu_total"  [t| Double |]
  ])

-- | CPU activity of an idle node. This can be used as a default
-- value for offline nodes.
emptyCPUavgload :: CPUavgload
emptyCPUavgload = CPUavgload { cavCpuNumber = 1
                             , cavCpus = [ 0.0 ]
                             , cavCpuTotal = 0.0
                             }

-- | This is the format of the data parsed by the input file.
$(buildObject "CPUstat" "cs"
  [ simpleField "name"       [t| String |]
  , simpleField "user"       [t| Integer |]
  , simpleField "nice"       [t| Integer |]
  , simpleField "system"     [t| Integer |]
  , simpleField "idle"       [t| Integer |]
  , simpleField "iowait"     [t| Integer |]
  , simpleField "irq"        [t| Integer |]
  , simpleField "softirq"    [t| Integer |]
  , simpleField "steal"      [t| Integer |]
  , simpleField "guest"      [t| Integer |]
  , simpleField "guest_nice" [t| Integer |]
  ])
