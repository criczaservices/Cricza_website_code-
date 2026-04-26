def check_braces(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    stack = []
    for i, char in enumerate(content):
        if char in "({[":
            stack.append((char, i))
        elif char in ")}]":
            if not stack:
                print(f"Unmatched closing '{char}' at index {i}")
                return False
            top, _ = stack.pop()
            if (top == '(' and char != ')') or \
               (top == '{' and char != '}') or \
               (top == '[' and char != ']'):
                print(f"Mismatched closing '{char}' for '{top}' at index {i}")
                return False
    if stack:
        print(f"Unmatched opening brackets remaining: {stack}")
        return False
    print("Brackets are balanced!")
    return True

check_braces(r'd:\cricza building\static\js\main.js')
