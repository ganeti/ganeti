{-# LANGUAGE TemplateHaskell #-}
{-| Diskstats data types

This module holds the definition of the data types describing the status of the
disks according to the information contained in @/proc/diskstats@.

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
module Ganeti.Storage.Diskstats.Types
  ( Diskstats(..)
  ) where

import Ganeti.THH


-- | This is the format of the report produced by each data collector.
$(buildObject "Diskstats" "ds"
  [ simpleField "major"        [t| Int |]
  , simpleField "minor"        [t| Int |]
  , simpleField "name"         [t| String |]
  , simpleField "readsNum"        [t| Int |]
  , simpleField "mergedReads"  [t| Int |]
  , simpleField "secRead"      [t| Int |]
  , simpleField "timeRead"     [t| Int |]
  , simpleField "writes"       [t| Int |]
  , simpleField "mergedWrites" [t| Int |]
  , simpleField "secWritten"   [t| Int |]
  , simpleField "timeWrite"    [t| Int |]
  , simpleField "ios"          [t| Int |]
  , simpleField "timeIO"       [t| Int |]
  , simpleField "wIOmillis"    [t| Int |]
  ])
