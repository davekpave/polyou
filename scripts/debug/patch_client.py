import os
import json

state_file = "logs/active_positions.json"
if os.path.exists(state_file):
    with open(state_file, "r") as f:
        data = json.load(f)
    print("Found active positions:", len(data))
    
    with open(state_file, "w") as f:
        json.dump({}, f)
    print("Wiped active_positions.json to stop the spam loop!")

# Now patch execution_client.py to not spam if post_order fails (e.g. from manual sell)
path = "src/polyou/execution/execution_client.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# I want to change:
"""
        except Exception as e:
            logger.exception("Failed to close position | token_id=%s error=%s", token_id, str(e))
            return False
"""
# To:
# If "amount" or "balance" in str(e).lower() or "sufficient" in str(e).lower(), remove it from active_positions because they sold it manually.

new_except = """
        except Exception as e:
            logger.exception("Failed to close position | token_id=%s error=%s", token_id, str(e))
            if "balance" in str(e).lower() or "amount" in str(e).lower() or "sufficient" in str(e).lower() or "exceeds" in str(e).lower():
                logger.warning("Detected manual sell or insufficient balance, removing %s from active positions", token_id)
                self.active_positions.pop(token_id, None)
                self._persist_state()
            return False
"""

text = text.replace("""        except Exception as e:
            logger.exception("Failed to close position | token_id=%s error=%s", token_id, str(e))
            return False""", new_except.strip('\n'))

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("Patched execution_client.py")
