# Tool Specifications

## read_pr
**Description**: Retrieve the details and diff of a pull request.
**Command**: `gh pr view <number> --json title,body,state,author,labels,reviews,comments`
**Diff Command**: `gh pr diff <number>`

## post_comment
**Description**: Post a comment to a pull request.
**Command**: `gh pr comment <number> --body "<body>"`
