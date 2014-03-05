{-# LANGUAGE TemplateHaskell #-}

{-| Helpers for creating various kinds of 'Field's.

They aren't directly needed for the Template Haskell code in Ganeti.THH,
so better keep them in a separate module.

-}

{-

Copyright (C) 2014 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.THH.Field
  ( specialNumericalField
  , timeAsDoubleField
  , timeStampFields
  , uuidFields
  , serialFields
  , TagSet
  , tagsFields
  ) where

import Control.Monad
import qualified Data.Set as Set
import Language.Haskell.TH
import qualified Text.JSON as JSON
import System.Time (ClockTime(..))

import Ganeti.JSON
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

-- * External functions and data types

-- | Timestamp fields description.
timeStampFields :: [Field]
timeStampFields = map (defaultField [| TOD 0 0 |] . timeAsDoubleField)
                      ["ctime", "mtime"]


-- | Serial number fields description.
serialFields :: [Field]
serialFields =
    [ renameField  "Serial" $ simpleField "serial_no" [t| Int |] ]

-- | UUID fields description.
uuidFields :: [Field]
uuidFields = [ simpleField "uuid" [t| String |] ]

-- | Tag set type alias.
type TagSet = Set.Set String

-- | Tag field description.
tagsFields :: [Field]
tagsFields = [ defaultField [| Set.empty |] $
               simpleField "tags" [t| TagSet |] ]
