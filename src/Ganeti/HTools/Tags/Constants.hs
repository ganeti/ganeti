{-| Tag constants

This module holds all the special tag prefixes honored
by Ganeti's htools. The module itself does not depend
on anything Ganeti specific so that it can be imported
anywhere.

-}

{-

Copyright (C) 2014, 2015 Google Inc.
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

module Ganeti.HTools.Tags.Constants
  ( exTagsPrefix
  , standbyPrefix
  , migrationPrefix
  , allowMigrationPrefix
  , locationPrefix
  , desiredLocationPrefix
  , standbyAuto
  , autoRepairTagPrefix
  , autoRepairTagEnabled
  , autoRepairTagPending
  , autoRepairTagResult
  , autoRepairTagSuspended
  ) where

-- | The exclusion tag prefix. Instance tags starting with this prefix
-- describe a service provided by the instance. Instances providing the
-- same service at not places on the same node.
exTagsPrefix :: String
exTagsPrefix = "htools:iextags:"

-- | The tag-prefix indicating that hsqueeze should consider a node
-- as being standby.
standbyPrefix :: String
standbyPrefix = "htools:standby:"

-- | The prefix for migration tags
migrationPrefix :: String
migrationPrefix = "htools:migration:"

-- | Prefix of tags allowing migration
allowMigrationPrefix :: String
allowMigrationPrefix = "htools:allowmigration:"

-- | The prefix for node location tags.
locationPrefix :: String
locationPrefix = "htools:nlocation:"

-- | The prefix for instance desired location tags.
desiredLocationPrefix :: String
desiredLocationPrefix = "htools:desiredlocation:"

-- | The tag to be added to nodes that were shutdown by hsqueeze.
standbyAuto :: String
standbyAuto = "htools:standby:auto"

-- | Auto-repair tag prefix
autoRepairTagPrefix :: String
autoRepairTagPrefix = "ganeti:watcher:autorepair:"

autoRepairTagEnabled :: String
autoRepairTagEnabled = autoRepairTagPrefix

autoRepairTagPending :: String
autoRepairTagPending = autoRepairTagPrefix ++ "pending:"

autoRepairTagResult :: String
autoRepairTagResult = autoRepairTagPrefix ++ "result:"

autoRepairTagSuspended :: String
autoRepairTagSuspended = autoRepairTagPrefix ++ "suspend:"

