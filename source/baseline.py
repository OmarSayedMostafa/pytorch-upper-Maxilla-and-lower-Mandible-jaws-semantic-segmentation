import os
import time
import numpy as np
import warnings
import random
import torch
import torch.nn as nn
import torch.optim as optim

from option import get_args
from learning.dataset import JawsDataset
from learning.learner import train_epoch, validate_epoch, predict
from learning.utils import get_dataloader, get_lossfunc, get_model

from helpers.helpers import plot_learning_curves
import torchvision.transforms.functional as TF
import warnings
warnings.filterwarnings('ignore')

def main(args): 
    # print("args : ", args)

    # Fix seed
    if args.seed is not None:
        torch.manual_seed(args.random_seed)
        torch.cuda.manual_seed(args.random_seed)
        torch.cuda.manual_seed_all(args.random_seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        np.random.seed(args.random_seed)
        random.seed(args.random_seed)
        warnings.warn('You have chosen to seed training. '
                      'This will turn on the CUDNN deterministic setting, '
                      'which can slow down your training considerably! '
                      'You may see unexpected behavior when restarting from checkpoints.')
    
    # Create directory to store run files
    args.save_path = os.path.join(args.save_path, args.experiment_name)
    if not os.path.isdir(args.save_path):
        os.makedirs(args.save_path + '/images')
    if not os.path.isdir(args.save_path + '/images/val'):
        os.makedirs(args.save_path + '/images/val')
        os.makedirs(args.save_path + '/images/test')
    
    Dataset = JawsDataset

    dataloaders = get_dataloader(Dataset, args)
    criterion = get_lossfunc(Dataset, args)
    model = get_model(Dataset, args)

    # optimizer = torch.optim.SGD(model.parameters(), lr=args.lr_init, momentum=args.lr_momentum, weight_decay=args.lr_weight_decay)
    optimizer = torch.optim.Adam(model.parameters(),lr=args.lr_init,  weight_decay=args.lr_weight_decay)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    # scheduler = optim.lr_scheduler.StepLR(optimizer=optimizer, step_size=int(args.schedule_steps), gamma=0.5)
    # Initialize metrics
    best_miou = 0.0
    metrics = {'train_loss' : [],
               'train_acc' : [],
               'val_acc' : [],
               'val_loss' : [],
               'miou' : []}
    start_epoch = 0
    
    # Push model to GPU
    if torch.cuda.is_available():
        model = torch.nn.DataParallel(model).cuda()
        print('Model pushed to {} GPU(s), type {}.'.format(torch.cuda.device_count(), torch.cuda.get_device_name(0)))
        
    # Resume training from checkpoint
    if args.weights:
        print('Resuming training from {}.'.format(args.weights))
        checkpoint = torch.load(args.weights)
        model.load_state_dict(checkpoint['model_state_dict'], strict=True)
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        metrics = checkpoint['metrics']
        best_miou = checkpoint['best_miou']
        start_epoch = checkpoint['epoch']+1
    
    

    # No training, only running prediction on test set
    if args.predict:
        checkpoint = torch.load(args.save_path + '/best_weights.pth.tar')
        model.load_state_dict(checkpoint['model_state_dict'], strict=True)
        print('Loaded model weights from {}'.format(args.save_path + '/best_weights.pth.tar'))
        # Create results directory
        if not os.path.isdir(args.save_path + '/images/val'):
            os.makedirs(args.save_path + '/images/val')
        if not os.path.isdir(args.save_path + '/images/test'):
            os.makedirs(args.save_path + '/images/test')

        val_acc, val_loss, miou = validate_epoch(dataloaders['test'], model, criterion, 0,
                                                 Dataset.classLabels, Dataset.validClasses, void=Dataset.voidClass,
                                                 maskColors=Dataset.mask_colors, folder=args.save_path, args=args, mode='test')
        return
    
    # Generate log file
    with open(args.save_path + '/log_epoch.csv', 'a') as epoch_log:
        epoch_log.write('epoch, train loss, val loss, train acc, val acc, miou\n')
    
    since = time.time()
    
    for epoch in range(start_epoch, args.epochs):
        # Train
        print('--- Training ---\n', args.dataset_path)
        train_loss, train_acc = train_epoch(dataloaders['train'], model, criterion, optimizer, scheduler, epoch,Dataset.classLabels, Dataset.validClasses, void=Dataset.voidClass, args=args)
        metrics['train_loss'].append(train_loss)
        metrics['train_acc'].append(train_acc)
        print('Epoch {} train loss: {:.4f}, acc: {:.4f}'.format(epoch,train_loss,train_acc))
        
        # Validate
        print('--- Validation ---\n', args.dataset_path)
        val_acc, val_loss, miou = validate_epoch(dataloaders['val'], model, criterion, epoch,
                                                 Dataset.classLabels, Dataset.validClasses, void=Dataset.voidClass,
                                                 maskColors=Dataset.mask_colors, folder=args.save_path, args=args, mode='val')
        metrics['val_acc'].append(val_acc)
        metrics['val_loss'].append(val_loss)
        ['miou'].append(miou)
        
        # Write logs
        with open(args.save_path + '/log_epoch.csv', 'a') as epoch_log:
            epoch_log.write('{}, {:.5f}, {:.5f}, {:.5f}, {:.5f}, {:.5f}\n'.format(
                    epoch, train_loss, val_loss, train_acc, val_acc, miou))
        
        # Save checkpoint
        torch.save({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'best_miou': best_miou,
            'metrics': metrics,
            }, args.save_path + '/checkpoint.pth.tar')
        
        # Save best model to file
        if miou > best_miou:
            print('mIoU improved from {:.4f} to {:.4f}.'.format(best_miou, miou))
            best_miou = miou
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                }, args.save_path + '/best_weights.pth.tar')
                
    time_elapsed = time.time() - since
    print('Training complete in {:.0f}m {:.0f}s'.format(
        time_elapsed // 60, time_elapsed % 60))
    
    # plot_learning_curves(metrics, args)

    # Load best model
    checkpoint = torch.load(args.save_path + '/best_weights.pth.tar')
    model.load_state_dict(checkpoint['model_state_dict'], strict=True)
    print('Loaded best model weights (epoch {}) from {}/best_weights.pth.tar'.format(checkpoint['epoch'], args.save_path))
    
    # Create results directory
    if not os.path.isdir(args.save_path + '/images/val'):
        os.makedirs(args.save_path + '/images/val')

    if not os.path.isdir(args.save_path + '/images/test'):
        os.makedirs(args.save_path + '/images/test')

    print('--- Test ---\n', args.dataset_path)
    # Run prediction on validation set. For predicting on test set, simple replace 'val' by 'test'
    val_acc, val_loss, miou = validate_epoch(dataloaders['test'], model, criterion, 0,
                                                 Dataset.classLabels, Dataset.validClasses, void=Dataset.voidClass,
                                                 maskColors=Dataset.mask_colors, folder=args.save_path, args=args, mode='test')

    
if __name__ == '__main__':
    args = get_args()
    main(args)
