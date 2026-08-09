"""
智码云 - 用户认证测试脚本
"""

import requests
import json
from datetime import datetime

BASE_URL = 'http://localhost:5000'

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_result(test_name, success, response_data):
    status = "✅ 成功" if success else "❌ 失败"
    print(f"{status} | {test_name}")
    print(f"  响应: {json.dumps(response_data, ensure_ascii=False, indent=2)}\n")

def test_authentication():
    """测试认证系统"""
    
    print_header("智码云用户认证系统测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"服务地址: {BASE_URL}\n")
    
    # 测试1：用户注册
    print_header("测试1: 用户注册")
    
    test_user = {
        'username': f'testuser_{int(datetime.now().timestamp())}',
        'email': f'test_{int(datetime.now().timestamp())}@example.com',
        'password': 'password123'
    }
    
    try:
        response = requests.post(f'{BASE_URL}/api/register', json=test_user)
        data = response.json()
        success = response.status_code == 200 and data.get('success')
        print_result("注册新用户", success, data)
        
        if success:
            user_id = data.get('user_id')
            username = data.get('username')
        else:
            print("❌ 注册失败，停止测试")
            return False
            
    except Exception as e:
        print(f"❌ 异常: {e}\n")
        return False
    
    # 测试2：用户名重复注册
    print_header("测试2: 用户名重复验证")
    
    try:
        response = requests.post(f'{BASE_URL}/api/register', json=test_user)
        data = response.json()
        success = response.status_code == 400 and '邮箱已被使用' in data.get('error', '')
        print_result("用户名重复检查", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试3：邮箱重复注册
    print_header("测试3: 邮箱重复验证")
    
    duplicate_email_user = {
        'username': f'testuser2_{int(datetime.now().timestamp())}',
        'email': test_user['email'],  # 使用相同邮箱
        'password': 'password123'
    }
    
    try:
        response = requests.post(f'{BASE_URL}/api/register', json=duplicate_email_user)
        data = response.json()
        success = response.status_code == 400 and '邮箱已被注册' in data.get('error', '')
        print_result("邮箱重复检查", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试4：用户登录
    print_header("测试4: 用户登录")
    
    login_data = {
        'username': test_user['username'],
        'password': test_user['password']
    }
    
    try:
        session = requests.Session()
        response = session.post(f'{BASE_URL}/api/login', json=login_data)
        data = response.json()
        success = response.status_code == 200 and data.get('success')
        print_result("用户登录", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
        return False
    
    # 测试5：错误密码登录
    print_header("测试5: 错误密码验证")
    
    wrong_login = {
        'username': test_user['username'],
        'password': 'wrongpassword'
    }
    
    try:
        response = session.post(f'{BASE_URL}/api/login', json=wrong_login)
        data = response.json()
        success = response.status_code == 401 and '邮箱或用户名或密码错误' in data.get('error', '')
        print_result("错误密码拒绝", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试6：检查认证状态
    print_header("测试6: 检查认证状态")
    
    try:
        response = session.get(f'{BASE_URL}/api/check_auth')
        data = response.json()
        success = data.get('authenticated') == True and data.get('username') == test_user['username']
        print_result("认证状态检查", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试7：获取用户信息
    print_header("测试7: 获取用户信息")
    
    try:
        response = session.get(f'{BASE_URL}/api/user_profile')
        data = response.json()
        success = response.status_code == 200 and data.get('username') == test_user['username']
        print_result("用户信息查询", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试8：用户登出
    print_header("测试8: 用户登出")
    
    try:
        response = session.post(f'{BASE_URL}/api/logout')
        data = response.json()
        success = data.get('success') == True
        print_result("用户登出", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试9：登出后认证状态
    print_header("测试9: 登出后认证状态")
    
    try:
        response = session.get(f'{BASE_URL}/api/check_auth')
        data = response.json()
        success = data.get('authenticated') == False
        print_result("登出状态验证", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    # 测试10：密码验证
    print_header("测试10: 密码强度验证")
    
    weak_password_user = {
        'username': 'weakpassuser',
        'email': 'weak@example.com',
        'password': 'weak'  # 少于6个字符
    }
    
    try:
        response = requests.post(f'{BASE_URL}/api/register', json=weak_password_user)
        data = response.json()
        success = response.status_code == 400 and '8个字符' in data.get('error', '')
        print_result("密码强度检查", success, data)
    except Exception as e:
        print(f"❌ 异常: {e}\n")
    
    print_header("✅ 测试完成")
    print("所有测试已完成！请检查上述结果。\n")
    
    return True

if __name__ == '__main__':
    try:
        test_authentication()
    except KeyboardInterrupt:
        print("\n\n❌ 测试被中断")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")