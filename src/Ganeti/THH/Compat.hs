{-# LANGUAGE CPP, TemplateHaskell #-}

{-| Shim library for supporting various Template Haskell versions

-}

{-

Copyright (C) 2018, 2021 Ganeti Project Contributors.
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
  ( gntInstanceD
  , gntDataD
  , extractDataDConstructors
  , myNotStrict
  , nonUnaryTupE
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

-- | DataD "constructor" function
--
-- Handle TH 2.11 and 2.12 changes in a transparent manner using the pre-2.11
-- API.
gntDataD :: Cxt -> Name -> [TyVarBndr] -> [Con] -> [Name] -> Dec
gntDataD x y z a b =
#if MIN_VERSION_template_haskell(2,12,0)
    DataD x y z Nothing a $ derivesFromNames b
#elif MIN_VERSION_template_haskell(2,11,0)
    DataD x y z Nothing a $ map ConT b
#else
    DataD x y z a b
#endif

-- | InstanceD "constructor" function
--
-- Handle TH 2.11 and 2.12 changes in a transparent manner using the pre-2.11
-- API.
gntInstanceD :: Cxt -> Type -> [Dec] -> Dec
gntInstanceD x y =
#if MIN_VERSION_template_haskell(2,11,0)
    InstanceD Nothing x y
#else
    InstanceD x y
#endif

-- | Extract constructors from a DataD instance
--
-- Handle TH 2.11 changes by abstracting pattern matching against DataD.
extractDataDConstructors :: Info -> Maybe [Con]
extractDataDConstructors info =
    case info of
#if MIN_VERSION_template_haskell(2,11,0)
    TyConI (DataD _ _ _ Nothing cons _) -> Just cons
#else
    TyConI (DataD _ _ _ cons _) -> Just cons
#endif
    _ -> Nothing

-- | Strict has been replaced by Bang, so redefine NotStrict in terms of the
-- latter.

#if MIN_VERSION_template_haskell(2,11,0)
myNotStrict :: Bang
myNotStrict = Bang NoSourceUnpackedness NoSourceStrictness
#else
myNotStrict = NotStrict
#endif

-- | TupE changed from '[Exp] -> Exp' to '[Maybe Exp] -> Exp'.
-- Provide the old signature for compatibility.
nonUnaryTupE :: [Exp] -> Exp
#if MIN_VERSION_template_haskell(2,16,0)
nonUnaryTupE es = TupE $ map Just es
#else
nonUnaryTupE es = TupE $ es
#endif
