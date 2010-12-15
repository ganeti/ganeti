{-| Module describing a node group.

-}

{-

Copyright (C) 2010 Google Inc.

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

module Ganeti.HTools.Group
    ( Group(..)
    , List
    , AssocList
    -- * Constructor
    , create
    , setIdx
    ) where

import qualified Ganeti.HTools.Container as Container

import qualified Ganeti.HTools.Types as T

-- * Type declarations

-- | The node group type.
data Group = Group
    { name        :: String        -- ^ The node name
    , uuid        :: T.GroupID     -- ^ The UUID of the group
    , idx         :: T.Gdx         -- ^ Internal index for book-keeping
    , allocPolicy :: T.AllocPolicy -- ^ The allocation policy for this group
    } deriving (Show, Eq)

-- Note: we use the name as the alias, and the UUID as the official
-- name
instance T.Element Group where
    nameOf     = uuid
    idxOf      = idx
    setAlias   = setName
    setIdx     = setIdx
    allNames n = [name n, uuid n]

-- | A simple name for the int, node association list.
type AssocList = [(T.Gdx, Group)]

-- | A simple name for a node map.
type List = Container.Container Group

-- * Initialization functions

-- | Create a new group.
create :: String -> T.GroupID -> T.AllocPolicy -> Group
create name_init id_init apol_init =
    Group { name        = name_init
          , uuid        = id_init
          , allocPolicy = apol_init
          , idx         = -1
          }

-- This is used only during the building of the data structures.
setIdx :: Group -> T.Gdx -> Group
setIdx t i = t {idx = i}

-- | Changes the alias.
--
-- This is used only during the building of the data structures.
setName :: Group -> String -> Group
setName t s = t { name = s }
