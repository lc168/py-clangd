/**
 * 红黑树 (Red-Black Tree) 完整 C 语言实现
 * 
 * 红黑树性质：
 * 1. 每个节点是红色或黑色
 * 2. 根节点是黑色
 * 3. 所有叶子(NIL)是黑色
 * 4. 红色节点的子节点必须是黑色（不能有连续红节点）
 * 5. 从任一节点到其每个叶子的所有路径包含相同数目的黑色节点
 */

#include <stdio.h>
#include <stdlib.h>

// ==================== 数据结构与类型定义 ====================

typedef enum { RED, BLACK } Color;

typedef struct RBNode {
    int key;                    // 键值
    Color color;                // 节点颜色
    struct RBNode *left;        // 左子节点
    struct RBNode *right;       // 右子节点
    struct RBNode *parent;      // 父节点
} RBNode;

typedef struct {
    RBNode *root;               // 根节点
    RBNode *nil;                // 哨兵节点（代表所有叶子NIL）
} RBTree;

// ==================== 辅助函数声明 ====================

RBNode* create_node(RBTree *tree, int key, Color color);
void left_rotate(RBTree *tree, RBNode *x);
void right_rotate(RBTree *tree, RBNode *y);
void rb_insert_fixup(RBTree *tree, RBNode *z);
void rb_delete_fixup(RBTree *tree, RBNode *x);
void rb_transplant(RBTree *tree, RBNode *u, RBNode *v);
RBNode* tree_minimum(RBTree *tree, RBNode *x);
RBNode* tree_maximum(RBTree *tree, RBNode *x);

// ==================== 树的基本操作 ====================

/**
 * 创建一个新的红黑树
 */
RBTree* rb_create() {
    RBTree *tree = (RBTree*)malloc(sizeof(RBTree));
    // 创建哨兵节点，所有叶子指向它
    tree->nil = (RBNode*)malloc(sizeof(RBNode));
    tree->nil->color = BLACK;
    tree->nil->left = tree->nil->right = tree->nil->parent = tree->nil;
    tree->root = tree->nil;
    return tree;
}

/**
 * 创建新节点
 */
RBNode* create_node(RBTree *tree, int key, Color color) {
    RBNode *node = (RBNode*)malloc(sizeof(RBNode));
    node->key = key;
    node->color = color;
    node->left = tree->nil;
    node->right = tree->nil;
    node->parent = tree->nil;
    return node;
}

/**
 * 查找节点
 */
RBNode* rb_search(RBTree *tree, int key) {
    RBNode *current = tree->root;
    while (current != tree->nil && key != current->key) {
        if (key < current->key)
            current = current->left;
        else
            current = current->right;
    }
    return current;
}

/**
 * 查找最小值节点
 */
RBNode* tree_minimum(RBTree *tree, RBNode *x) {
    while (x->left != tree->nil)
        x = x->left;
    return x;
}

/**
 * 查找最大值节点
 */
RBNode* tree_maximum(RBTree *tree, RBNode *x) {
    while (x->right != tree->nil)
        x = x->right;
    return x;
}

/**
 * 查找后继节点（中序遍历的下一个节点）
 */
RBNode* tree_successor(RBTree *tree, RBNode *x) {
    if (x->right != tree->nil)
        return tree_minimum(tree, x->right);
    RBNode *y = x->parent;
    while (y != tree->nil && x == y->right) {
        x = y;
        y = y->parent;
    }
    return y;
}

// ==================== 旋转操作 ====================

/**
 * 左旋：以x为支点进行左旋
 *       x              y
 *      / \            / \
 *     α   y    =>    x   γ
 *        / \        / \
 *       β   γ      α   β
 */
void left_rotate(RBTree *tree, RBNode *x) {
    RBNode *y = x->right;           // 设置y
    x->right = y->left;             // 将y的左子树转为x的右子树
    
    if (y->left != tree->nil)
        y->left->parent = x;
    
    y->parent = x->parent;          // 链接x的父节点到y
    
    if (x->parent == tree->nil)
        tree->root = y;
    else if (x == x->parent->left)
        x->parent->left = y;
    else
        x->parent->right = y;
    
    y->left = x;                    // 将x放在y的左边
    x->parent = y;
}

/**
 * 右旋：以y为支点进行右旋（左旋的镜像）
 *         y            x
 *        / \          / \
 *       x   γ   =>   α   y
 *      / \              / \
 *     α   β            β   γ
 */
void right_rotate(RBTree *tree, RBNode *y) {
    RBNode *x = y->left;
    y->left = x->right;
    
    if (x->right != tree->nil)
        x->right->parent = y;
    
    x->parent = y->parent;
    
    if (y->parent == tree->nil)
        tree->root = x;
    else if (y == y->parent->right)
        y->parent->right = x;
    else
        y->parent->left = x;
    
    x->right = y;
    y->parent = x;
}

// ==================== 插入操作 ====================

/**
 * 插入修复：解决插入可能破坏的红黑树性质
 * 主要处理：性质4（不能有连续红节点）
 */
void rb_insert_fixup(RBTree *tree, RBNode *z) {
    while (z->parent->color == RED) {
        if (z->parent == z->parent->parent->left) {  // 父节点是左子
            RBNode *y = z->parent->parent->right;     // 叔节点
            
            if (y->color == RED) {
                // Case 1: 叔节点是红色
                // 将父节点和叔节点变黑，祖父节点变红，然后向上检查
                z->parent->color = BLACK;
                y->color = BLACK;
                z->parent->parent->color = RED;
                z = z->parent->parent;
            } else {
                if (z == z->parent->right) {
                    // Case 2: 叔节点黑，且z是右子（转为Case 3）
                    z = z->parent;
                    left_rotate(tree, z);
                }
                // Case 3: 叔节点黑，z是左子
                z->parent->color = BLACK;
                z->parent->parent->color = RED;
                right_rotate(tree, z->parent->parent);
            }
        } else {  // 父节点是右子（镜像情况）
            RBNode *y = z->parent->parent->left;
            
            if (y->color == RED) {
                z->parent->color = BLACK;
                y->color = BLACK;
                z->parent->parent->color = RED;
                z = z->parent->parent;
            } else {
                if (z == z->parent->left) {
                    z = z->parent;
                    right_rotate(tree, z);
                }
                z->parent->color = BLACK;
                z->parent->parent->color = RED;
                left_rotate(tree, z->parent->parent);
            }
        }
    }
    tree->root->color = BLACK;  // 确保根节点为黑（性质2）
}

/**
 * 插入节点
 */
void rb_insert(RBTree *tree, int key) {
    RBNode *z = create_node(tree, key, RED);  // 新节点初始为红色
    RBNode *y = tree->nil;
    RBNode *x = tree->root;
    
    // 找到插入位置
    while (x != tree->nil) {
        y = x;
        if (z->key < x->key)
            x = x->left;
        else if (z->key > x->key)
            x = x->right;
        else {
            // 键已存在，不插入
            free(z);
            return;
        }
    }
    
    z->parent = y;
    
    if (y == tree->nil)
        tree->root = z;
    else if (z->key < y->key)
        y->left = z;
    else
        y->right = z;
    
    // 如果插入的是根节点，直接设为黑色
    if (z->parent == tree->nil) {
        z->color = BLACK;
        return;
    }
    
    // 如果父节点是根节点，不需要修复
    if (z->parent->parent == tree->nil)
        return;
    
    // 修复红黑树性质
    rb_insert_fixup(tree, z);
}

// ==================== 删除操作 ====================

/**
 * 用v替换u的位置（不改变子树结构，只改变父子链接）
 */
void rb_transplant(RBTree *tree, RBNode *u, RBNode *v) {
    if (u->parent == tree->nil)
        tree->root = v;
    else if (u == u->parent->left)
        u->parent->left = v;
    else
        u->parent->right = v;
    v->parent = u->parent;
}

/**
 * 删除修复：解决删除可能破坏的红黑树性质
 * 主要处理：性质5（黑高度平衡）
 */
void rb_delete_fixup(RBTree *tree, RBNode *x) {
    while (x != tree->root && x->color == BLACK) {
        if (x == x->parent->left) {  // x是左子
            RBNode *w = x->parent->right;  // 兄弟节点
            
            if (w->color == RED) {
                // Case 1: 兄弟是红色（转为Case 2/3/4）
                w->color = BLACK;
                x->parent->color = RED;
                left_rotate(tree, x->parent);
                w = x->parent->right;
            }
            
            if (w->left->color == BLACK && w->right->color == BLACK) {
                // Case 2: 兄弟是黑色，且两个侄子都是黑色
                w->color = RED;
                x = x->parent;
            } else {
                if (w->right->color == BLACK) {
                    // Case 3: 兄弟黑，左侄红，右侄黑（转为Case 4）
                    w->left->color = BLACK;
                    w->color = RED;
                    right_rotate(tree, w);
                    w = x->parent->right;
                }
                // Case 4: 兄弟黑，右侄红
                w->color = x->parent->color;
                x->parent->color = BLACK;
                w->right->color = BLACK;
                left_rotate(tree, x->parent);
                x = tree->root;
            }
        } else {  // x是右子（镜像情况）
            RBNode *w = x->parent->left;
            
            if (w->color == RED) {
                w->color = BLACK;
                x->parent->color = RED;
                right_rotate(tree, x->parent);
                w = x->parent->left;
            }
            
            if (w->right->color == BLACK && w->left->color == BLACK) {
                w->color = RED;
                x = x->parent;
            } else {
                if (w->left->color == BLACK) {
                    w->right->color = BLACK;
                    w->color = RED;
                    left_rotate(tree, w);
                    w = x->parent->left;
                }
                w->color = x->parent->color;
                x->parent->color = BLACK;
                w->left->color = BLACK;
                right_rotate(tree, x->parent);
                x = tree->root;
            }
        }
    }
    x->color = BLACK;
}

/**
 * 删除节点
 */
int rb_delete(RBTree *tree, int key) {
    RBNode *z = rb_search(tree, key);
    if (z == tree->nil) return 0;  // 未找到
    
    RBNode *y = z;
    RBNode *x;
    Color y_original_color = y->color;
    
    if (z->left == tree->nil) {
        // 只有右子或没有子节点
        x = z->right;
        rb_transplant(tree, z, z->right);
    } else if (z->right == tree->nil) {
        // 只有左子
        x = z->left;
        rb_transplant(tree, z, z->left);
    } else {
        // 有两个子节点：找后继
        y = tree_minimum(tree, z->right);
        y_original_color = y->color;
        x = y->right;
        
        if (y->parent == z) {
            x->parent = y;
        } else {
            rb_transplant(tree, y, y->right);
            y->right = z->right;
            y->right->parent = y;
        }
        
        rb_transplant(tree, z, y);
        y->left = z->left;
        y->left->parent = y;
        y->color = z->color;
    }
    
    free(z);
    
    // 如果删除的是黑色节点，需要修复
    if (y_original_color == BLACK)
        rb_delete_fixup(tree, x);
    
    return 1;
}

// ==================== 遍历与可视化 ====================

/**
 * 中序遍历
 */
void inorder_traversal(RBTree *tree, RBNode *node) {
    if (node != tree->nil) {
        inorder_traversal(tree, node->left);
        printf("%d(%s) ", node->key, node->color == RED ? "R" : "B");
        inorder_traversal(tree, node->right);
    }
}

/**
 * 打印树结构（横向显示，便于理解结构）
 */
void print_tree_helper(RBTree *tree, RBNode *node, int space, int is_left) {
    if (node == tree->nil) return;
    
    space += 4;
    
    // 先打印右子树
    print_tree_helper(tree, node->right, space, 0);
    
    // 打印当前节点
    printf("\n");
    for (int i = 4; i < space; i++)
        printf(" ");
    if (is_left == 0 && node->parent != tree->nil && node->parent->right == node)
        printf("/-");
    else if (is_left == 1 && node->parent != tree->nil && node->parent->left == node)
        printf("\\-");
    else
        printf("  ");
    
    printf("%d[%s]", node->key, node->color == RED ? "R" : "B");
    
    // 打印左子树
    print_tree_helper(tree, node->left, space, 1);
}

void print_tree(RBTree *tree) {
    if (tree->root == tree->nil) {
        printf("Empty tree\n");
        return;
    }
    print_tree_helper(tree, tree->root, 0, -1);
    printf("\n");
}

// ==================== 内存释放 ====================

void free_tree_helper(RBTree *tree, RBNode *node) {
    if (node != tree->nil) {
        free_tree_helper(tree, node->left);
        free_tree_helper(tree, node->right);
        free(node);
    }
}

void rb_destroy(RBTree *tree) {
    free_tree_helper(tree, tree->root);
    free(tree->nil);
    free(tree);
}

// ==================== 测试主函数 ====================

int main() {
    printf("=== 红黑树 C 语言实现测试 ===\n\n");
    
    RBTree *tree = rb_create();
    
    // 测试插入
    printf("1. 插入测试：插入 10, 20, 30, 15, 25, 5, 1, 7\n");
    int keys[] = {10, 20, 30, 15, 25, 5, 1, 7};
    for (int i = 0; i < 8; i++) {
        printf("插入 %d...\n", keys[i]);
        rb_insert(tree, keys[i]);
    }
    
    printf("\n中序遍历结果：");
    inorder_traversal(tree, tree->root);
    printf("\n");
    
    printf("\n树结构：\n");
    print_tree(tree);
    
    // 测试查找
    printf("\n2. 查找测试：\n");
    int search_keys[] = {15, 100, 7};
    for (int i = 0; i < 3; i++) {
        RBNode *result = rb_search(tree, search_keys[i]);
        if (result != tree->nil)
            printf("找到 %d，颜色：%s\n", search_keys[i], 
                   result->color == RED ? "红" : "黑");
        else
            printf("未找到 %d\n", search_keys[i]);
    }
    
    // 测试删除
    printf("\n3. 删除测试：\n");
    
    printf("删除 20（有两个子节点的节点）...\n");
    rb_delete(tree, 20);
    printf("中序遍历：");
    inorder_traversal(tree, tree->root);
    printf("\n");
    
    printf("删除 1（红色叶子节点）...\n");
    rb_delete(tree, 1);
    printf("中序遍历：");
    inorder_traversal(tree, tree->root);
    printf("\n");
    
    printf("删除 10（根节点）...\n");
    rb_delete(tree, 10);
    printf("中序遍历：");
    inorder_traversal(tree, tree->root);
    printf("\n");
    
    printf("\n最终树结构：\n");
    print_tree(tree);
    
    // 清理
    rb_destroy(tree);
    printf("\n内存已释放，程序结束。\n");
    
    return 0;
}