import streamlit as st
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import numpy as np
import plotly.graph_objects as go
import cv2
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense,Dropout,Flatten
from tensorflow.keras.optimizers import Adamax
from tensorflow.keras.metrics import Precision,Recall
import google.generativeai as genai
import PIL.Image
import os 
from dotenv import load_dotenv
load_dotenv()

genai.configure(api_key=os.getenv('GENAI_API_KEY'))
output_dir = 'saliency_maps'
os.makedirs(output_dir,exist_ok=True)

def generate_explanation(img_path,model_prediction,confidence):
    prompt  = f"""
You are an expert neurologist. You are tasked with explaining a saliency of a brain tumor MRI scan.
The saliency map was generated by a deep learning model that was trained to classify brain tumors 
as either glioma, meningioma, pituitary, or no tumor.

The saliency map highlights the regions of the image that the machine learning model is focusing on to make the prediction.
The deep learning model predicted the image to be of class '{model_prediction}' with a confidence of {confidence * 100}%.

In your response:
- Explain what regions of the brain the model is focusing on, based on the saliency map. Refer to the regions highlighted in light cyan, those are the regions where the model is focusing on.
- Explain possible reasons why the model made the prediction it did/
- Don't mention anythling like 'The saliency map highlights the regions the model is focusing on, which are light cyan'
- Keep your explanation to 4 setences max.

Let's think step by step about this. Verify step by step.
"""
    img = PIL.Image.open(img_path)
    model = genai.GenerativeModel(model_name='gemini-1.5-flash')
    response = model.generate_content([prompt,img])
    return response.text
def generate_saliency_map(model, img_array, class_index, img_size):
    """
    Creates a visual representation (saliency map) highlighting areas of a brain MRI image that are most important for the model's prediction. Thus, enhancing transparency and trust in the output.
    """
    # Compute gradients of the target class with respect to the input image
    with tf.GradientTape() as tape:
        img_tensor = tf.convert_to_tensor(img_array)
        tape.watch(img_tensor)
        predictions = model(img_tensor)
        target_class = predictions[:, class_index]
    # Gradient processing
    gradients = tape.gradient(target_class, img_tensor)
    gradients = tf.math.abs(gradients)
    gradients = tf.reduce_max(gradients, axis=-1)
    gradients = gradients.numpy().squeeze()
    # Resize gradients to match original image size
    gradients = cv2.resize(gradients, img_size)
    # Create a circular mask for the brain area
    center = (gradients.shape[0] // 2, gradients.shape[1] // 2)
    radius = min(center[0], center[1]) - 10
    y, x = np.ogrid[:gradients.shape[0], :gradients.shape[1]]
    mask = (x - center[0])**2 + (y - center[1])**2 <= radius**2
    # Apply mask to gradients
    gradients = gradients * mask
    # Normalize only the brain area
    brain_gradients = gradients[mask]
    if brain_gradients.max() > brain_gradients.min():
        brain_gradients = (brain_gradients - brain_gradients.min()) / (brain_gradients.max() - brain_gradients.min())
    gradients[mask] = brain_gradients
    # Apply a higher threshold
    threshold = np.percentile(gradients[mask], 80)
    gradients[gradients < threshold] = 0
    # Apply more aggressive smoothing
    gradients = cv2.GaussianBlur(gradients, (11, 11), 0)
    # Create a heatmap overlay with enhanced contrast
    heatmap = cv2.applyColorMap(np.uint8(255 * gradients), cv2.COLORMAP_JET)
    heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
    # Resize heatmap to match original image size
    heatmap = cv2.resize(heatmap, img_size)
    # Superimpose the heatmap on original image with increased opacity
    original_img = image.img_to_array(img)
    superimposed_img = heatmap * 0.7 + original_img * 0.3
    superimposed_img = superimposed_img.astype(np.uint8)
    # Save the original uploaded image
    img_path = os.path.join(output_dir, uploaded_file.name)
    with open(img_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    # Define path and save the saliency map
    saliency_map_path = f'saliency_maps/{uploaded_file.name}'
    cv2.imwrite(saliency_map_path, cv2.cvtColor(superimposed_img, cv2.COLOR_RGB2BGR))
    return superimposed_img


def load_xception_model(model_path):
    img_shape = (299,299,3)
    base_model = tf.keras.applications.Xception(include_top=False,weights='imagenet',input_shape=img_shape,pooling='max')

    #Look into neural network and understand this.
    model = Sequential([
        base_model,
        #Flatten takes the multi-dimensional feature map and flattens it to 1 dimension.
        Flatten(),
        #Randomly drops 30% of neurons to prevent overfitting (where model is to well trained on data and can't generalize on unseen data)
        Dropout(rate=0.3),
        #Repeat process of creating feature maps, except this time at a higher level/layer identifying bigger features
        #ReLU zeroes out all negative values of feature maps. This means all weak signals are ignored.
        Dense(128,activation='relu'),
        Dropout(rate=0.25),
        #In our final classification, we want probabilities for each class, given by softmax, the 4 neurons represent the 4 final classes.
        Dense(4,activation='softmax')
    ])
    model.build((None,)+ img_shape)
    model.compile(Adamax(learning_rate=0.001),
                loss = 'categorical_crossentropy',
                metrics = ['accuracy',Precision(),Recall()]
                )
    model.load_weights(model_path)
    return model


st.title('Brain Tumor Classification')
st.write('Upload an image of a brain MRI scan to classify')

uploaded_file = st.file_uploader("Choose an image...", type=['jpg','jpeg','png'])

if uploaded_file is not None:
    selected_model = st.radio(
        'Select Model',
        ('Transfer-Learning Model','Custom Model')
    )
    if selected_model =='Transfer-Learning Model':
        model = load_xception_model('xceptions_model.weights.h5')
        img_size = (299,299)
    else:
        model = load_model('cnn_model.h5')
        img_size = (224,224)

    labels = ['Glioma','Meningioma','No Tumor','Pituitary']
    img = image.load_img(uploaded_file,target_size=img_size)
    img_array =image.img_to_array(img)
    img_array = np.expand_dims(img_array,axis=0)
    img_array /=255.0

    prediction = model.predict(img_array)
    class_index = np.argmax(prediction[0])
    result = labels[class_index]

    
    st.write('# Predictions:')
    value = prediction[0][class_index] * 100
    st.write(f'## Predicted Class: {result} Confidence: {value:.2f}% ')
    for label, prob in zip(labels,prediction[0]):
        st.write(f'{label}: {prob:.4f}')

    saliency_map = generate_saliency_map(model,img_array,class_index,img_size)
    col1,col2 = st.columns(2)
    with col1:
        st.image(uploaded_file,caption='Uploaded Image',use_container_width=True)
    with col2:
        st.image(saliency_map,caption='Saliency Map',use_container_width=True)

    saliency_map_path = f'saliency_maps/{uploaded_file.name}'
    explanation = generate_explanation(saliency_map_path,result,prediction[0][class_index])

    st.write('## Explanation')
    st.write(explanation)
