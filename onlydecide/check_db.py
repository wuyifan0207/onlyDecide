import sqlite3

def check_database_structure():
    try:
        conn = sqlite3.connect('decisions.db')
        cur = conn.cursor()
        
        # 检查表结构
        cur.execute('PRAGMA table_info(decisions)')
        columns = cur.fetchall()
        
        print("数据库字段结构:")
        for col in columns:
            print(f"字段 {col[1]}: 类型 {col[2]}, 允许空值: {col[3]}, 默认值: {col[4]}")
        
        # 检查是否有executed字段
        executed_exists = any(col[1] == 'executed' for col in columns)
        print(f"\n是否存在executed字段: {executed_exists}")
        
        conn.close()
        return executed_exists
        
    except Exception as e:
        print(f"检查数据库时出错: {e}")
        return False

if __name__ == "__main__":
    check_database_structure()