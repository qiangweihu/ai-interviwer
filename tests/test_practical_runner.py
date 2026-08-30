import json
import unittest

from backend.runner_worker import execute


class PracticalRunnerTests(unittest.TestCase):
    def test_python_public_and_hidden_data_only_tests(self):
        payload = {
            "task_type": "coding",
            "language": "python",
            "source": "import sys\ndata=list(map(int, sys.stdin.read().split())); print(sum(data[1:]) if data else 0)",
            "tests": [
                {"input": "4\n1 2 3 4\n", "output": "10\n"},
                {"input": "3\n-1 5 2\n", "output": "6\n"},
            ],
        }
        result = execute(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["passed"], 2)

    def test_timeout_and_compile_error_are_reported(self):
        timeout = execute({"task_type": "coding", "language": "python", "source": "while True: pass", "tests": [{"input": "", "output": ""}]})
        self.assertEqual(timeout["runtime_error"], "运行超时")
        compile_error = execute({"task_type": "coding", "language": "python", "source": "def broken(:", "tests": [{"input": "", "output": ""}]})
        self.assertEqual(compile_error["status"], "failed")

    def test_sql_is_read_only_and_results_are_structured(self):
        payload = {
            "task_type": "practical",
            "practical_type": "sql",
            "language": "sql",
            "source": "SELECT name FROM users ORDER BY id",
            "materials": {"schema": "CREATE TABLE users(id INT, name TEXT);", "seed": "INSERT INTO users VALUES (1, 'a'), (2, 'b');"},
            "tests": [{"rows": [["a"], ["b"]]}],
        }
        self.assertEqual(execute(payload)["status"], "ok")
        payload["source"] = "DROP TABLE users"
        self.assertIn("只允许只读", execute(payload)["runtime_error"])


if __name__ == "__main__":
    unittest.main()
