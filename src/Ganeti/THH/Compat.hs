{-# LANGUAGE CPP, TemplateHaskell #-}

{-| Shim library for supporting various Template Haskell versions

-}

{-

Copyright (C) 2018 Ganeti Project Contributors.
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

module Ganeti.THH.Compat
  ( derivesFromNames
  ) where

import Language.Haskell.TH

-- | Convert Names to DerivClauses
--
-- template-haskell 2.12 (GHC 8.2) has changed the DataD class of
-- constructors to expect [DerivClause] instead of [Names]. Handle this in a
-- backwards-compatible way.
#if MIN_VERSION_template_haskell(2,12,0)
derivesFromNames :: [Name] -> [DerivClause]
derivesFromNames names = [DerivClause Nothing $ map ConT names]
#else
derivesFromNames :: [Name] -> Cxt
derivesFromNames names = map ConT names
#endif
