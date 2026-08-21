import glob
import re

fixed_logic = """                    now = glfw.get_time()
                    if now - getattr(self, "_last_config_check", 0) > 1.0:
                        self._last_config_check = now
                        try:
                            from config import cfg
                            cfg.reload_if_changed()
                        except:
                            pass"""

for filepath in glob.glob('modules/*.py'):
    if filepath.endswith('config.py'): continue
    if filepath.endswith('vu.py'): continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The bad code from previous script run:
    bad_pattern = r'(\s*)now = glfw\.get_time\(\)\s*if now - getattr\(self, "_last_config_check", 0\) > 1\.0:\s*self\._last_config_check = now\s*try:\s*from config import cfg\s*cfg\.reload_if_changed\(\)\s*except:\s*pass'
    
    # We strip out any existing fixed logic.
    content = re.sub(bad_pattern, '', content)
    
    # Now, insert the fixed logic right after `while self.running`
    loop_pattern = r'(while self\.running( and not glfw\.window_should_close\(self\.window\))?:)'
    
    # Check if we can find the loop
    if re.search(loop_pattern, content):
        content = re.sub(loop_pattern, r'\1\n' + fixed_logic, content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filepath}")
    else:
        print(f"Could not find loop in {filepath}")
