# Contribution Process

### tl;dr;

[See the GitHub flow tutorial.](https://guides.github.com/introduction/flow/)
1.  Fork the Ganeti repo on GitHub
2.  Make changes in a feature branch, probably based off the master branch.
2.  Test using "make pylint; make hlint; make py-tests; make hs-tests"
3.  Send your changes for review by opening a Pull Request.
4.  Sign the [Google CLA](https://cla.developers.google.com/).
5.  Address the reviewer comments by making new commits and ask PTAL.
6.  Wait for your Pull Request to be accepted.

### 1. Forking the Repo

The Ganeti project uses Pull Requests to accept contributions. In order to do so
you must first [fork](https://help.github.com/articles/fork-a-repo/) the Ganeti
repo: https://github.com/ganeti/ganeti. After that, clone your fork and add the
original repository as the upstream:

```
git clone git@github.com:<username>/ganeti.git
git remote add upstream git@github.com:ganeti/ganeti.git
```

### 2. Merging Upstream changes

Important: Before starting a new patch it is a good idea to
[merge all the upstream changes](https://help.github.com/articles/syncing-a-fork/):

```
git fetch upstream
git checkout <branch>
git merge upstream/<branch>
```

### 3. Creating your feature branch
We recommend using
[feature branches](https://www.atlassian.com/git/tutorials/using-branches)
in your repo instead of commit directly to the master and/or stable branches.
Without feature branches you could have a local clone in a separate folder named
after the feature. This would work well as long as you don't want to make
parallel pull requests or backup your local work on github. If your local
folders map to respective feature branches on your personal fork on github, you
can work in parallel on multiple features with backing up local commits on
github as well as work on multiple pull requests.

Let's say you want to patch an existing issue on branch <existing_branchname>.
Then:
```
git checkout <existing_branchname>
git checkout -b <feature_branchname>
```

Try to use a descriptive name for the feature branch. Names like
"feature-<issue_id>", "bug-<issue_id>" are good when referring to an existing
bug/feature request. Using a name related to the theme of the changes is also a
good idea (i.e.: "predictive_locking").

### 4. Making your changes

Make the changes you need/want to do on your feature branch. Make as many
commits as you want, making sure that the commit messages are small and concise
within the context of your changes. The commit messages are going to be useful
for the reviewer, so be reasonable. Favor small Pull Requests as they are easier
to review and they provide feedback early. Avoid making huge changes just to see
the reviewer asking you to restart from scratch..

Remember to use the --signoff flag when committing. You may also push these
changes to your personal fork by running `git push origin <feature_branchname>`

### 5. Testing your changes

`make pylint; make hlint; make py-tests; make hs-tests`

### 6. Sending changes for review

Once you and the tests are happy enough with your changes, push your changes to
your personal fork. After that,
[create a pull request](https://help.github.com/articles/creating-a-pull-request/)
from your feature branch to the target branch in the ganeti/ganeti repo.

The Pull Request message should explain WHY these changes are needed and, if
they're not trivial, explain HOW they are being implemented. Also, make sure
that it follows the canonical commit message criteria: 

* It MUST have a single line heading with no period, at most 80 characters
* It MUST have a description, as described above
* It MUST have a "Signed-off-by: author@org" line (Same generated when using
  the --signoff flag)

### 7. Google CLA

If you've never contributed to a Google project before, you will be asked to
sign a Contributor License Agreement (CLA). The googlebot will ask you to do so
if needed. This CLA can be signed in https://cla.developers.google.com/

### 8. Addressing Reviewers comments
If your pull request is more than a one-line fix, it will probably have some
comments from a reviewer. The reviewer might help you to identify some
typos/bugs, to improve your documentation and to improve your
design/implementation. Don't feel bad about this, this is actually good both for
you and for the community as a whole! Also, feel free to push back the reviewer
if you think you have a point. This is a conversation, not a fight.

In order to fix issues spotted by the reviewer, make the additional changes
locally and commit them on the same feature branch of the pull request.  Do not
alter commits already submitted to review (e.g. by using rebase), but add your
changes as new commits. The pull request review UI does not store history of the
changes, so changing the commits would erase the context that was commented on
during the review.

1.  Make changes using your favorite editor.
2.  Run the tests
3.  git commit -m "Fixing typos spotted by the reviewer" --signoff
4.  git push origin
5.  Make changes to the Pull Request message as needed
    1.  Respond to individual comments as needed
    2.  Ask the reviewer to take a look (PTAL) in the main pull request thread,
        as individual comments on changes won't send notifications to the reviewer.

Keep doing this until you receive an Approval from the reviewer.

### 9. Pushing your changes
After receiving all the approvals needed, the reviewer will pull your changes to
the repo. Congratulations!

## Pull Request Example

Let's say that you found a bug in which a stack overflow is caused whenever your
ternary_search function receive a specific set of inputs. You open an issue on
GitHub detailing your findings and it creates the issue 1234.

To fix this issue you first create a local branch called "bug/1234". You first
either add a set of regression tests or fix the existing tests to prove that the
invalid behavior is actually happening. You then decide to commit these changes:

```
git commit -m "Add regression tests for bug/1234" --sign-off
(optional) git push origin
```
After reading through the code you finally find the source of the issue and fix
it. You then commit these changes:

```
git commit -m "Fix algorithm for input X" --sign-off
(optional) git push origin
```
Now both you and the tests are happy with the changes. So you then create a pull
request from your fork to the base branch. The Pull Request message should be
detailed, describing the WHY and the HOW of your changes. You then use the
following message on your Pull Request:

```
Fix bug in ternary_search that would cause an stack overflow for specific inputs

Whenever three consecutive numbers were used as inputs for the ternary_search
function it would end up causing a stack overflow. This caused issues whenever
the user tried to do action X. We fix this by handling these as a special case.
This closes #1234.

Signed-off-by: Your Name <yourname@yourorg.com>
```
Your Pull Request is then assigned to some reviewers. They notice that you forgot
to add some comments to your code, so they ask you to do so. You then add the
comments, push these changes to your fork. You then ask the reviewer to take
another look on your Pull Request (PTAL = Please Take Another Look). These
changes are automatically sent to the reviewer:

```
git commit -m "Adding comments for the fix" --sign-off
git push origin
```

The reviewer is now happy as well, so he/she approves the pull request, adds the
reviewed-by tag. When all the approvals are given, a reviewer then squashs all
your commits into a single canonical commit, using the Pull Request message as
the commit message. Now your changes are committed to the repo, so you can
celebrate!
