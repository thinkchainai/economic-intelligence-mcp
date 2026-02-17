#!/bin/bash
# Build the .mcpb Desktop Extension file.
# Requires: npm (for npx)
# Output: economic-intelligence-mcp.mcpb in the repo root
set -e

echo "Building economic-intelligence-mcp.mcpb..."
npx @anthropic-ai/mcpb pack
echo "Done. Double-click economic-intelligence-mcp.mcpb to install in Claude Desktop."
