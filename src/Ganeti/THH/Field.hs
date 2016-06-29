{-# LANGUAGE TemplateHaskell #-}

{-| Helpers for creating various kinds of 'Field's.

They aren't directly needed for the Template Haskell code in Ganeti.THH,
so better keep them in a separate module.

-}

{-

Copyright (C) 2014 Google Inc.
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

module Ganeti.THH.Field
  ( specialNumericalField
  , timeAsDoubleField
  , timeStampFields
  , uuidFields
  , serialFields
  , TagSet
  , tagsFields
  , fileModeAsIntField
  , processIdField
  ) where

import Control.Monad
import qualified Data.ByteString as BS
import qualified Data.Set as Set
import Language.Haskell.TH
import qualified Text.JSON as JSON
import System.Posix.Types (FileMode, ProcessID)
import System.Time (ClockTime(..))

import Ganeti.JSON (TimeAsDoubleJSON(..))
import Ganeti.THH

-- * Internal functions

-- | Wrapper around a special parse function, suitable as field-parsing
-- function.
numericalReadFn :: JSON.JSON a => (String -> JSON.Result a)
                   -> [(String, JSON.JSValue)] -> JSON.JSValue -> JSON.Result a
numericalReadFn _ _ v@(JSON.JSRational _ _) = JSON.readJSON v
numericalReadFn f _ (JSON.JSString x) = f $ JSON.fromJSString x
numericalReadFn _ _ _ = JSON.Error "A numerical field has to be a number or\
                                   \ a string."

-- | Sets the read function to also accept string parsable by the given
-- function.
specialNumericalField :: Name -> Field -> Field
specialNumericalField f field =
     field { fieldRead = Just (appE (varE 'numericalReadFn) (varE f)) }

-- | Creates a new mandatory field that reads time as the (floating point)
-- number of seconds since the standard UNIX epoch, and represents it in
-- Haskell as 'ClockTime'.
timeAsDoubleField :: String -> Field
timeAsDoubleField fname =
  (simpleField fname [t| ClockTime |])
    { fieldRead = Just $ [| \_ -> liftM unTimeAsDoubleJSON . JSON.readJSON |]
    , fieldShow = Just $ [| \c -> (JSON.showJSON $ TimeAsDoubleJSON c, []) |]
    }

-- | A helper function for creating fields whose Haskell representation is
-- 'Integral' and which are serialized as numbers.
integralField :: Q Type -> String -> Field
integralField typq fname =
  let (~->) = appT . appT arrowT  -- constructs an arrow type
      (~::) = sigE . varE         -- (f ~:: t) constructs (f :: t)
  in (simpleField fname typq)
      { fieldRead = Just $
        [| \_ -> liftM $('fromInteger ~:: (conT ''Integer ~-> typq))
                   . JSON.readJSON |]
      , fieldShow = Just $
          [| \c -> (JSON.showJSON
                    . $('toInteger ~:: (typq ~-> conT ''Integer))
                    $ c, []) |]
      }

-- * External functions and data types

-- | Timestamp fields description.
timeStampFields :: [Field]
timeStampFields = map (defaultField [| TOD 0 0 |] . timeAsDoubleField)
                      ["ctime", "mtime"]


-- | Serial number fields description.
serialFields :: [Field]
serialFields =
    [ presentInForthcoming . renameField  "Serial"
        $ simpleField "serial_no" [t| Int |] ]

-- | UUID fields description.
uuidFields :: [Field]
uuidFields = [ presentInForthcoming $ simpleField "uuid" [t| BS.ByteString |] ]

-- | Tag set type alias.
type TagSet = Set.Set String

-- | Tag field description.
tagsFields :: [Field]
tagsFields = [ defaultField [| Set.empty |] $
               simpleField "tags" [t| TagSet |] ]

-- ** Fields related to POSIX data types

-- | Creates a new mandatory field that reads a file mode in the standard
-- POSIX file mode representation. The Haskell type of the field is 'FileMode'.
fileModeAsIntField :: String -> Field
fileModeAsIntField = integralField [t| FileMode |]

-- | Creates a new mandatory field that contains a POSIX process ID.
processIdField :: String -> Field
processIdField = integralField [t| ProcessID |]
