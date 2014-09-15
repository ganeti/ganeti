{-| Ganeti lock-related types and type classes

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

module Ganeti.Locking.Types
  ( Lock
  , lockImplications
  ) where

{-| The type class of being a lock

As usual, locks need to come with an order, the lock order, and
be an instance of Show, so that malformed requests can meaningfully
be reported.

Additionally, in Ganeti we also have group locks, like a lock for all
nodes. While those group locks contain infinitely many locks, the set
of locks a single lock is included in is always finite, and usually
very small. So we take this association from a lock to the locks it
is (strictly) included in as additional data of the type class.

It is a prerequisite that whenever 'a' is implied in 'b', then all locks
that are in the lock order between 'a' and 'b' are also implied in 'b'.

-}

class (Ord a, Show a) => Lock a where
  lockImplications :: a -> [a]
