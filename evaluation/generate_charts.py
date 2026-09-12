import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# Configuration
BASELINE_CSV = 'eval_baseline.csv'
PROACTIVE_CSV = 'eval_proactive.csv'
OUTPUT_DIR = 'evaluation_results'

def calculate_metrics(df):
    """Calculate MAE and RMSE for EWMA predictor."""
    # Filter out absolute zero startup rows if they dominate
    active_df = df[df['utilization'] > 0]
    if active_df.empty:
        active_df = df
        
    actual = active_df['utilization'].values[1:]
    predicted = active_df['predicted_utilization'].values[:-1]
    
    if len(actual) == 0:
        return 0.0, 0.0
        
    mae = np.mean(np.abs(actual - predicted))
    rmse = np.sqrt(np.mean((actual - predicted)**2))
    return mae, rmse

def plot_prediction_accuracy(df, target_link, output_path):
    plt.figure(figsize=(10, 5))
    link_df = df[df['link_id'] == target_link].copy()
    
    # Skip leading zeros
    non_zero_idx = link_df[link_df['utilization'] > 0].index
    if len(non_zero_idx) > 0:
        first_idx = non_zero_idx[0]
        # Keep 5 points before the first non-zero for context
        start_idx = max(0, link_df.index.get_loc(first_idx) - 5)
        link_df = link_df.iloc[start_idx:]
    
    link_df = link_df.reset_index(drop=True)
    subset = link_df.head(100)
    
    plt.plot(subset.index, subset['utilization'], label='Actual Utilization', color='blue', linewidth=2)
    plt.plot(subset.index, subset['predicted_utilization'].shift(1), label='Predicted Utilization (EWMA)', color='red', linestyle='--')
    plt.title(f'EWMA Prediction Accuracy on Link {target_link}')
    plt.xlabel('Time (Sync Intervals)')
    plt.ylabel('Utilization (%)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def plot_congestion_comparison(df_base, df_pro, target_link, output_path):
    base_link = df_base[df_base['link_id'] == target_link].reset_index() if df_base is not None else None
    pro_link = df_pro[df_pro['link_id'] == target_link].reset_index() if df_pro is not None else None
    
    plt.figure(figsize=(12, 6))
    if base_link is not None and not base_link.empty:
        plt.plot(base_link.index, base_link['utilization'], label='Baseline (Static Routing)', color='red')
    if pro_link is not None and not pro_link.empty:
        plt.plot(pro_link.index, pro_link['utilization'], label='Digital Twin (Proactive Reroute)', color='green')
        
    plt.axhline(y=85, color='orange', linestyle=':', label='Congestion Threshold (85%)')
    plt.title(f'Congestion Avoidance on Bottleneck Link: {target_link}')
    plt.xlabel('Time (Sync Intervals)')
    plt.ylabel('Utilization (%)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def plot_peak_utilization_bar(df_base, df_pro, target_link, output_path):
    base_peak = df_base[df_base['link_id'] == target_link]['utilization'].max() if df_base is not None else 0
    pro_peak = df_pro[df_pro['link_id'] == target_link]['utilization'].max() if df_pro is not None else 0
    
    labels = ['Baseline (Static)', 'Digital Twin (Proactive)']
    peaks = [base_peak, pro_peak]
    colors = ['red', 'green']
    
    plt.figure(figsize=(8, 6))
    bars = plt.bar(labels, peaks, color=colors, width=0.5)
    plt.axhline(y=85, color='orange', linestyle=':', label='Threshold (85%)')
    
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 1, f"{round(yval, 1)}%", ha='center', va='bottom', fontweight='bold')
        
    plt.title(f'Peak Utilization on {target_link}')
    plt.ylabel('Max Utilization (%)')
    plt.ylim(0, max(100, max(peaks) + 10))
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    df_base = None
    df_pro = None
    
    cols = ['timestamp', 'link_id', 'src_port', 'dst_port', 'tx_rate_bytes', 'utilization', 'predicted_utilization']
    
    if os.path.exists(BASELINE_CSV):
        df_base = pd.read_csv(BASELINE_CSV, names=cols, header=0)
        print(f"Loaded {BASELINE_CSV} ({len(df_base)} rows)")
        mae, rmse = calculate_metrics(df_base)
        print(f"[EWMA Predictor Baseline] MAE: {mae:.2f}%, RMSE: {rmse:.2f}%")
    else:
        print(f"WARNING: {BASELINE_CSV} not found. Skip baseline plotting.")
        
    if os.path.exists(PROACTIVE_CSV):
        df_pro = pd.read_csv(PROACTIVE_CSV, names=cols, header=0)
        print(f"Loaded {PROACTIVE_CSV} ({len(df_pro)} rows)")
        mae, rmse = calculate_metrics(df_pro)
        print(f"[EWMA Predictor Proactive] MAE: {mae:.2f}%, RMSE: {rmse:.2f}%")
    else:
        print(f"WARNING: {PROACTIVE_CSV} not found. Skip proactive plotting.")
        
    if df_base is not None or df_pro is not None:
        target_link = None
        if df_base is not None:
            target_link = df_base.groupby('link_id')['utilization'].max().idxmax()
        elif df_pro is not None:
            target_link = df_pro.groupby('link_id')['utilization'].max().idxmax()
            
        print(f"Generating comparison charts for most congested link: {target_link}")
        if df_base is not None:
            plot_prediction_accuracy(df_base, target_link, os.path.join(OUTPUT_DIR, 'ewma_accuracy_baseline.png'))
        plot_congestion_comparison(df_base, df_pro, target_link, os.path.join(OUTPUT_DIR, 'congestion_over_time.png'))
        plot_peak_utilization_bar(df_base, df_pro, target_link, os.path.join(OUTPUT_DIR, 'peak_utilization.png'))
        print(f"Charts saved to {OUTPUT_DIR}/")

if __name__ == '__main__':
    main()

