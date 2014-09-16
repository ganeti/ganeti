{-| Implementation of Ganeti filter queries.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.
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

module Ganeti.Query.FilterRules
  ( fieldsMap
  ) where

import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types


-- | List of all lock fields.
filterFields :: FieldList FilterRule NoDataRuntime
filterFields =
  [ (FieldDefinition "watermark" "Watermark" QFTOther "Highest job ID used\
                                                       \ at the time when the\
                                                       \ filter was added",
     FieldSimple (rsNormal . frWatermark), QffNormal)
  , (FieldDefinition "priority" "Priority" QFTOther "Filter priority",
     FieldSimple (rsNormal . frPriority), QffNormal)
  , (FieldDefinition "predicates" "Predicates" QFTOther "List of filter\
                                                         \ predicates",
     FieldSimple (rsNormal . frPredicates), QffNormal)
  , (FieldDefinition "action" "Action" QFTOther "Filter action",
     FieldSimple (rsNormal . frAction), QffNormal)
  , (FieldDefinition "reason_trail" "ReasonTrail" QFTOther "Reason why this\
                                                            \ filter was\
                                                            \ added",
     FieldSimple (rsNormal . frReasonTrail), QffNormal)
  , (FieldDefinition "uuid" "UUID" QFTOther "Filter ID",
     FieldSimple (rsNormal . frUuid), QffNormal)
  ]

-- | The lock fields map.
fieldsMap :: FieldMap FilterRule NoDataRuntime
fieldsMap = fieldListToFieldMap filterFields
