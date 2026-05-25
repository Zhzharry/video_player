# 演示素材目录

把用于实验展示的图片放入 `demo_assets/input/`，支持 jpg、png、webp、bmp。

生成每种灰度算法的原图/处理图对比结果：

```bash
python3 demo_generate_results.py
```

输出文件会写入 `demo_assets/output/`：

- `gray_comparison.png`
- `invert_comparison.png`
- `brightness_comparison.png`
- `contrast_comparison.png`
- `binary_comparison.png`
- `gamma_comparison.png`
- `equalized_comparison.png`
