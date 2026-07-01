# Claude Evolution System

Git commits use conventional-style.

## Performance Guidelines

- **Batch tool calls** where possible to minimize latency and token waste. Avoid repeated individual calls when a single batched operation can achieve the same result.
- **Avoid redundant operations** — check current state before making a call that may have been made already.
- **Prefer bulk operations** (e.g., one `Bash` command that does multiple things) over multiple sequential calls.

## Error Handling

- **Prevent unknown errors** — always validate input parameters and ensure all required fields are provided before making tool calls.
- **Avoid user_prompt errors** — when constructing prompts, ensure all variables are properly formatted and no template placeholders remain unsubstituted.
- **If you encounter an error**, verify the tool name and arguments before retrying. Use available documentation or schema to confirm correctness.

## Efficiency

- **Batch tool calls**: When performing multiple similar operations (e.g., reading files, searching code), batch them into a single tool call if possible to reduce round-trips.
- **Avoid rapid repeated calls**: If you find yourself calling the same tool rapidly in a loop, consider aggregating the requests or using a more efficient approach.